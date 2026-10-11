namespace PisoNet.Client.Core;

/// <summary>Connection state of the station client.</summary>
public enum ConnectionState
{
    /// <summary>Initial state or retrying the first contact.</summary>
    Connecting,

    /// <summary>Heartbeats are succeeding; state is synchronized.</summary>
    Connected,

    /// <summary>Transient failure; retrying automatically.</summary>
    Disconnected,

    /// <summary>Repeated failures; the server appears unreachable.</summary>
    ServerUnavailable,

    /// <summary>
    /// The server rejected the station credentials (revoked or
    /// rotated). The client stops retrying until the operator
    /// re-enrolls or rotates credentials.
    /// </summary>
    AuthenticationFailed,
}
