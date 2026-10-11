namespace PisoNet.Client.Core;

/// <summary>
/// Processes commands delivered with heartbeat responses.
///
/// Safety rules:
/// - Only the documented command types ("lock", "unlock") are
///   implemented; anything else is ignored and never executed.
/// - Expired commands are never applied.
/// - Delivery is idempotent: a command is applied at most once
///   per client run, even if the server redelivers it after a
///   failed acknowledgement.
/// - Acknowledgement failures leave the command unacknowledged
///   server-side for redelivery; the applied state set is only
///   updated after a successful acknowledgement.
/// </summary>
public sealed class CommandProcessor
{
    private readonly StationApiClient _apiClient;
    private readonly StationStateModel _state;
    private readonly HashSet<long> _acknowledgedCommandIds = new();

    /// <summary>
    /// Applies lock/unlock commands to the station state
    /// and acknowledges them with the server.
    /// </summary>
    /// <param name="apiClient">Authenticated station API client.</param>
    /// <param name="state">Station state to update.</param>
    public CommandProcessor(StationApiClient apiClient, StationStateModel state)
    {
        _apiClient = apiClient;
        _state = state;
    }

    /// <summary>
    /// Applies each pending command at most once, then
    /// acknowledges it. Expired and unknown command types
    /// are never applied.
    /// </summary>
    /// <param name="commands">Commands delivered with a heartbeat.</param>
    /// <param name="serverTime">Server time (Unix epoch seconds).</param>
    /// <param name="cancellationToken">Cancels acknowledgement.</param>
    public async Task ProcessAsync(
        IReadOnlyList<PendingCommandDto> commands,
        long serverTime,
        CancellationToken cancellationToken = default)
    {
        foreach (var command in commands)
        {
            if (_acknowledgedCommandIds.Contains(command.Id))
            {
                // Duplicate delivery: already applied and acknowledged.
                continue;
            }

            if (command.ExpiresAt <= serverTime)
            {
                // Expired: never apply. The server purges expired
                // commands on the next heartbeat.
                continue;
            }

            switch (command.CommandType)
            {
                case "lock":
                    _state.IsAdminLocked = true;
                    break;
                case "unlock":
                    _state.IsAdminLocked = false;
                    break;
                default:
                    // Unsupported command type: do not apply and do
                    // not acknowledge, so the server retires it at
                    // its delivery deadline (TTL).
                    continue;
            }

            try
            {
                await _apiClient.AcknowledgeCommandAsync(command.Id, cancellationToken);
            }
            catch (StationAuthenticationException)
            {
                // Credential problems must surface immediately.
                throw;
            }
            catch (StationProtocolException)
            {
                // Non-transient protocol error: leave unacknowledged
                // and unprocessed so the next heartbeat retries.
                continue;
            }
            catch (Exception)
            {
                // Transient failure (network/timeout): leave
                // unacknowledged so the server redelivers.
                continue;
            }

            // Applied and acknowledged exactly once.
            _acknowledgedCommandIds.Add(command.Id);
        }
    }
}
