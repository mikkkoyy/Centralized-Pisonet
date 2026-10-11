namespace PisoNet.Client.Core;

/// <summary>
/// Lifecycle-managed heartbeat loop.
///
/// Guarantees:
/// - At most one in-flight heartbeat per station.
/// - Every request is sequence-tagged; stale responses never
///   overwrite newer station state.
/// - Bounded retries with exponential backoff and jitter.
/// - Authentication failures halt the loop (no infinite retry
///   against revoked credentials).
/// - Clean cancellation and shutdown.
/// - A failed heartbeat never unlocks the station, extends
///   paid time, or creates a session.
/// </summary>
public sealed class HeartbeatService : IAsyncDisposable
{
    // Consecutive transient failures before reporting ServerUnavailable.
    private const int ServerUnavailableThreshold = 3;
    private static readonly TimeSpan MaxBackoff = TimeSpan.FromSeconds(30);

    private readonly ClientConfiguration _configuration;
    private readonly StationApiClient _apiClient;
    private readonly StationStateModel _state;
    private readonly SessionCountdown _countdown;
    private readonly CommandProcessor _commandProcessor;

    private readonly CancellationTokenSource _stopping = new();
    private readonly Random _jitter = new();

    private long _sequence;
    private long _lastProcessedSequence;
    private int _consecutiveFailures;
    private int _inFlight;
    private bool _halted;
    private Task? _loopTask;

    /// <summary>Raised on the thread pool whenever station state changes.</summary>
    public event Action? StateChanged;

    /// <summary>
    /// Creates the heartbeat loop. The loop is not started
    /// until <see cref="Start"/> is called.
    /// </summary>
    /// <param name="configuration">Client configuration.</param>
    /// <param name="apiClient">Authenticated station API client.</param>
    /// <param name="state">Station state updated by the loop.</param>
    /// <param name="countdown">Server-anchored session countdown.</param>
    /// <param name="commandProcessor">Processor for delivered commands.</param>
    public HeartbeatService(
        ClientConfiguration configuration,
        StationApiClient apiClient,
        StationStateModel state,
        SessionCountdown countdown,
        CommandProcessor commandProcessor)
    {
        _configuration = configuration;
        _apiClient = apiClient;
        _state = state;
        _countdown = countdown;
        _commandProcessor = commandProcessor;
    }

    /// <summary>True once the loop has halted (authentication or protocol failure).</summary>
    public bool IsHalted => _halted;

    /// <summary>Starts the heartbeat loop. Safe to call once.</summary>
    public void Start()
    {
        if (_loopTask is not null)
        {
            return;
        }

        _state.Connection = ConnectionState.Connecting;
        _state.Message = "Connecting to server...";
        OnStateChanged();
        _loopTask = LoopAsync(_stopping.Token);
    }

    /// <summary>Cancels the loop and awaits its completion.</summary>
    public async Task StopAsync()
    {
        if (_loopTask is null)
        {
            return;
        }

        _stopping.Cancel();
        try
        {
            await _loopTask;
        }
        catch (OperationCanceledException)
        {
            // Expected during shutdown.
        }
        catch (Exception)
        {
            // Loop exceptions are already handled per-iteration.
        }

        _loopTask = null;
    }

    private async Task LoopAsync(CancellationToken cancellationToken)
    {
        while (!cancellationToken.IsCancellationRequested && !_halted)
        {
            try
            {
                await HeartbeatOnceAsync(cancellationToken);
            }
            catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
            {
                break;
            }
            catch (Exception exception)
            {
                HandleFailure(exception);
            }

            if (_halted)
            {
                break;
            }

            var delay = NextDelay();
            try
            {
                await Task.Delay(delay, cancellationToken);
            }
            catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
            {
                break;
            }
        }
    }

    /// <summary>
    /// Performs a single heartbeat. Skipped when a heartbeat is
    /// already in flight (single-flight guarantee).
    /// </summary>
    internal async Task HeartbeatOnceAsync(CancellationToken cancellationToken)
    {
        if (Interlocked.CompareExchange(ref _inFlight, 1, 0) != 0)
        {
            return;
        }

        try
        {
            var sequence = Interlocked.Increment(ref _sequence);
            var response = await _apiClient.HeartbeatAsync(cancellationToken);

            // Reject stale responses: only apply state from the
            // newest request.
            if (sequence <= Interlocked.Read(ref _lastProcessedSequence))
            {
                return;
            }

            ApplyHeartbeat(response, sequence);

            // Command acknowledgement happens inside the same
            // single-flight section, so commands are processed in
            // delivery order and never overlap.
            await _commandProcessor.ProcessAsync(
                response.Commands ?? [],
                response.ServerTime,
                cancellationToken);

            OnStateChanged();
        }
        finally
        {
            Interlocked.Exchange(ref _inFlight, 0);
        }
    }

    /// <summary>
    /// Applies a heartbeat response to the station state.
    /// Called by the loop; internal for testing.
    /// </summary>
    internal void ApplyHeartbeat(HeartbeatResponse response, long sequence)
    {
        if (sequence <= Interlocked.Read(ref _lastProcessedSequence))
        {
            return; // stale response: do not overwrite newer state
        }

        Interlocked.Exchange(ref _lastProcessedSequence, sequence);

        _consecutiveFailures = 0;
        _state.StationCode = response.StationCode;
        _state.Connection = ConnectionState.Connected;
        _state.Message = "Connected";
        _state.StationState = response.StationState;
        _state.IsLocked = response.Lock != "unlocked";
        _state.ServerTime = response.ServerTime;
        _state.LastHeartbeatAtUtc = DateTime.UtcNow;

        if (response.Session is { } session && session.RemainingSeconds > 0)
        {
            _countdown.Synchronize(session.RemainingSeconds);
            _state.SessionStatus = SessionStatus.Active;
            _state.RemainingSeconds = session.RemainingSeconds;
            _state.CurrentRemainingSeconds = session.RemainingSeconds;
        }
        else
        {
            var hadSession = _state.SessionStatus == SessionStatus.Active;
            _countdown.Reset();
            _state.SessionStatus = hadSession ? SessionStatus.Terminated : SessionStatus.None;
            _state.RemainingSeconds = 0;
            _state.CurrentRemainingSeconds = 0;
        }
    }

    /// <summary>Maps a failed heartbeat to an explicit connection state.</summary>
    internal void HandleFailure(Exception exception)
    {
        switch (exception)
        {
            case OperationCanceledException:
                // Shutdown in progress; leave state untouched.
                break;

            case StationAuthenticationException authenticationException:
                // Revoked or rotated credential: stop retrying and
                // require operator action.
                _halted = true;
                _state.Connection = ConnectionState.AuthenticationFailed;
                _state.Message =
                    "Station credentials were rejected (revoked or rotated). " +
                    "Re-enroll or rotate the credential from the dashboard.";
                OnStateChanged();
                break;

            case StationProtocolException protocolException:
                // Client/server incompatibility or invalid request:
                // retrying cannot help. Halt with an actionable error.
                _halted = true;
                _state.Connection = ConnectionState.Disconnected;
                _state.Message = $"Protocol error: {protocolException.Message}";
                OnStateChanged();
                break;

            default:
                // Network failure, DNS error, or timeout: transient.
                // Back off and retry; never treat as permission to
                // unlock or extend time.
                _consecutiveFailures++;
                var unavailable = _consecutiveFailures >= ServerUnavailableThreshold;
                _state.Connection = unavailable
                    ? ConnectionState.ServerUnavailable
                    : ConnectionState.Disconnected;
                _state.Message = unavailable
                    ? "Server unavailable. Retrying automatically."
                    : "Connection lost. Retrying automatically.";
                OnStateChanged();
                break;
        }
    }

    /// <summary>
    /// Heartbeat interval on success; bounded exponential backoff
    /// with jitter after failures.
    /// </summary>
    internal TimeSpan NextDelay()
    {
        if (_consecutiveFailures == 0)
        {
            return _configuration.HeartbeatInterval;
        }

        var backoffSeconds = Math.Min(
            Math.Pow(2, _consecutiveFailures - 1) * 2,
            MaxBackoff.TotalSeconds);
        var jitterSeconds = _jitter.NextDouble(); // 0..1s
        return TimeSpan.FromSeconds(backoffSeconds + jitterSeconds);
    }

    /// <summary>
    /// Refreshes the animated countdown from the server-anchored
    /// value. Called by the UI; never fabricates time.
    /// </summary>
    public void RefreshCountdown()
    {
        _state.CurrentRemainingSeconds = _state.IsStale
            ? _state.RemainingSeconds // frozen at last server value
            : _countdown.Current;
    }

    private void OnStateChanged() => StateChanged?.Invoke();

    /// <summary>Cancels the loop, awaits its completion, and disposes resources.</summary>
    public async ValueTask DisposeAsync()
    {
        await StopAsync();
        _stopping.Dispose();
        _apiClient.Dispose();
    }
}
