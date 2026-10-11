using System.Net;

namespace PisoNet.Client.Core.Tests;

public class HeartbeatServiceTests
{
    private static ClientConfiguration Configuration() => new()
    {
        ServerUrl = "http://127.0.0.1:8000",
        StationCode = "PISO-01",
        HeartbeatInterval = TimeSpan.FromSeconds(10),
    };

    private static HeartbeatResponse SuccessfulHeartbeat(
        long serverTime,
        string stationState = "available",
        string @lock = "locked",
        SessionStateDto? session = null,
        IReadOnlyList<PendingCommandDto>? commands = null) => new(
        "PISO-01", 1, serverTime, stationState, @lock, session, commands);

    [Fact]
    public void ApplyHeartbeatUpdatesConnectedState()
    {
        var service = CreateService(out var state, out _);
        const long serverTime = 1_700_000_000;

        service.ApplyHeartbeat(
            SuccessfulHeartbeat(serverTime, "occupied", "unlocked"),
            sequence: 1);

        Assert.Equal(ConnectionState.Connected, state.Connection);
        Assert.Equal("occupied", state.StationState);
        Assert.False(state.IsLocked); // unlocked while a session is active
        Assert.Equal(serverTime, state.ServerTime);
        Assert.NotNull(state.LastHeartbeatAtUtc);
        Assert.False(state.IsStale);
    }

    [Fact]
    public void ApplyHeartbeatSynchronizesSession()
    {
        var service = CreateService(out var state, out _);
        var session = new SessionStateDto(
            5, "active", 3600, 1_700_000_000, 1500);

        service.ApplyHeartbeat(
            SuccessfulHeartbeat(1_700_000_000, session: session),
            sequence: 1);

        Assert.Equal(SessionStatus.Active, state.SessionStatus);
        Assert.Equal(1500, state.RemainingSeconds);
        Assert.Equal(1500, state.CurrentRemainingSeconds);
    }

    [Fact]
    public void SessionEndingTransitionsActiveToTerminated()
    {
        var service = CreateService(out var state, out _);
        var session = new SessionStateDto(
            5, "active", 3600, 1_700_000_000, 1500);
        service.ApplyHeartbeat(
            SuccessfulHeartbeat(1, session: session), sequence: 1);

        service.ApplyHeartbeat(
            SuccessfulHeartbeat(2), sequence: 2);

        Assert.Equal(SessionStatus.Terminated, state.SessionStatus);
        Assert.Equal(0, state.CurrentRemainingSeconds);
    }

    [Fact]
    public void SessionAbsentFromStartStaysNone()
    {
        var service = CreateService(out var state, out _);

        service.ApplyHeartbeat(SuccessfulHeartbeat(1), sequence: 1);

        Assert.Equal(SessionStatus.None, state.SessionStatus);
    }

    [Fact]
    public void StaleSequenceIsRejected()
    {
        var service = CreateService(out var state, out _);

        service.ApplyHeartbeat(
            SuccessfulHeartbeat(1, "occupied"), sequence: 5);
        service.ApplyHeartbeat(
            SuccessfulHeartbeat(2, "available"), sequence: 3); // stale

        Assert.Equal("occupied", state.StationState);
    }

    [Fact]
    public void AuthenticationFailureHaltsAndRequiresOperator()
    {
        var service = CreateService(out var state, out _);

        service.HandleFailure(new StationAuthenticationException("revoked"));

        Assert.True(service.IsHalted);
        Assert.Equal(ConnectionState.AuthenticationFailed, state.Connection);
        Assert.Contains("Re-enroll", state.Message);
    }

    [Fact]
    public void ProtocolFailureHaltsWithActionableError()
    {
        var service = CreateService(out var state, out _);

        service.HandleFailure(new ProtocolVersionMismatchException("bad version"));

        Assert.True(service.IsHalted);
        Assert.Contains("Protocol error", state.Message);
    }

    [Fact]
    public void TransientFailuresEscalateToServerUnavailable()
    {
        var service = CreateService(out var state, out _);

        service.HandleFailure(new HttpRequestException("dns"));
        Assert.Equal(ConnectionState.Disconnected, state.Connection);
        Assert.False(service.IsHalted);

        service.HandleFailure(new HttpRequestException("dns"));
        Assert.Equal(ConnectionState.Disconnected, state.Connection);

        service.HandleFailure(new HttpRequestException("dns"));
        Assert.Equal(ConnectionState.ServerUnavailable, state.Connection);
        Assert.False(service.IsHalted); // still retrying automatically
    }

    [Fact]
    public void RecoveryResetsFailureCount()
    {
        var service = CreateService(out var state, out _);

        service.HandleFailure(new HttpRequestException("dns"));
        service.HandleFailure(new HttpRequestException("dns"));
        service.ApplyHeartbeat(SuccessfulHeartbeat(1), sequence: 1);
        service.HandleFailure(new HttpRequestException("dns"));

        Assert.Equal(ConnectionState.Disconnected, state.Connection);
    }

    [Fact]
    public void NextDelayUsesIntervalOnSuccessAndBackoffOnFailures()
    {
        var service = CreateService(out _, out var configuration);

        Assert.Equal(
            configuration.HeartbeatInterval,
            service.NextDelay());

        service.HandleFailure(new HttpRequestException("dns"));
        var firstBackoff = service.NextDelay();
        Assert.InRange(firstBackoff.TotalSeconds, 2, 3); // 2s + 0..1s jitter

        service.HandleFailure(new HttpRequestException("dns"));
        var secondBackoff = service.NextDelay();
        Assert.InRange(secondBackoff.TotalSeconds, 4, 5);

        for (var i = 0; i < 10; i++)
        {
            service.HandleFailure(new HttpRequestException("dns"));
        }

        var capped = service.NextDelay();
        Assert.InRange(capped.TotalSeconds, 30, 31); // capped at 30s
    }

    [Fact]
    public async Task SingleFlightPreventsConcurrentHeartbeats()
    {
        var release = new TaskCompletionSource<bool>();
        var callCount = 0;
        var handler = new ScriptedHandler(async (_, _) =>
        {
            Interlocked.Increment(ref callCount);
            await release.Task;
            return HttpResponses.Json(HttpStatusCode.OK,
                """{"station_code":"PISO-01","protocol_version":1,"server_time":1,"station_state":"available","lock":"locked","session":null,"commands":null}""");
        });

        using var apiClient = new StationApiClient(Configuration(), handler);
        var state = new StationStateModel();
        var service = new HeartbeatService(
            Configuration(), apiClient, state,
            new SessionCountdown(),
            new CommandProcessor(apiClient, state));

        var first = service.HeartbeatOnceAsync(default);
        var second = service.HeartbeatOnceAsync(default);

        // The second call observes the in-flight heartbeat and
        // returns immediately without touching the server.
        await second;

        release.TrySetResult(true);
        await first;

        Assert.Equal(1, callCount); // only one request ever reached the handler
    }

    [Fact]
    public async Task FailedHeartbeatNeverUnlocksTheStation()
    {
        var handler = new ScriptedHandler((_, _) =>
            Task.FromException<HttpResponseMessage>(
                new HttpRequestException("network down")));
        using var apiClient = new StationApiClient(Configuration(), handler);
        var state = new StationStateModel { IsAdminLocked = true };
        var service = new HeartbeatService(
            Configuration(), apiClient, state,
            new SessionCountdown(),
            new CommandProcessor(apiClient, state));

        // A failed heartbeat must not clear an administrator
        // lock or fabricate session time.
        await Assert.ThrowsAsync<HttpRequestException>(
            () => service.HeartbeatOnceAsync(default));

        Assert.True(state.IsAdminLocked);
        Assert.NotEqual(ConnectionState.Connected, state.Connection);
    }

    [Fact]
    public void RefreshCountdownIsFrozenWhileStale()
    {
        var service = CreateService(out var state, out _);
        var session = new SessionStateDto(
            5, "active", 3600, 1_700_000_000, 1500);
        service.ApplyHeartbeat(
            SuccessfulHeartbeat(1, session: session), sequence: 1);
        service.RefreshCountdown();
        var connected = state.CurrentRemainingSeconds;

        state.Connection = ConnectionState.Disconnected; // lost connection
        service.RefreshCountdown();

        // Frozen at the last server-authoritative value,
        // not animated forward.
        Assert.Equal(connected, state.CurrentRemainingSeconds);
    }

    private static HeartbeatService CreateService(
        out StationStateModel state,
        out ClientConfiguration configuration)
    {
        configuration = Configuration();
        state = new StationStateModel();
        var apiClient = new StationApiClient(configuration);
        return new HeartbeatService(
            configuration,
            apiClient,
            state,
            new SessionCountdown(),
            new CommandProcessor(apiClient, state));
    }
}
