namespace PisoNet.Client.Core;

/// <summary>
/// UI-agnostic station state. The server is authoritative for
/// every field except <see cref="CurrentRemainingSeconds"/>, which
/// is a locally animated interpolation of the last server value
/// and is marked stale while disconnected.
/// </summary>
public sealed class StationStateModel
{
    /// <summary>Station identifier this state belongs to.</summary>
    public string StationCode { get; set; } = string.Empty;

    /// <summary>Current connection state of the station client.</summary>
    public ConnectionState Connection { get; set; } = ConnectionState.Disconnected;

    /// <summary>Human-readable status message for display.</summary>
    public string Message { get; set; } = "Not connected.";

    /// <summary>Server-reported station state: available | occupied | offline | revoked.</summary>
    public string StationState { get; set; } = string.Empty;

    /// <summary>Server-reported session lock (unlocked only while an
    /// unexpired session is active).</summary>
    public bool IsLocked { get; set; } = true;

    /// <summary>Set by an administrator "lock" command; cleared by
    /// "unlock". Independent of the session lock above so the
    /// banner survives heartbeats that report no session.</summary>
    public bool IsAdminLocked { get; set; }

    /// <summary>Session lifecycle as observed by the client.</summary>
    public SessionStatus SessionStatus { get; set; } = SessionStatus.None;

    /// <summary>Server-authoritative remaining seconds at the last successful heartbeat.</summary>
    public int RemainingSeconds { get; set; }

    /// <summary>Animated countdown between synchronizations; 0 when stale.</summary>
    public int CurrentRemainingSeconds { get; set; }

    /// <summary>Server time (Unix epoch seconds) from the last heartbeat.</summary>
    public long ServerTime { get; set; }

    /// <summary>UTC time of the last successful heartbeat.</summary>
    public DateTime? LastHeartbeatAtUtc { get; set; }

    /// <summary>True when the displayed state has not been confirmed by the server recently.</summary>
    public bool IsStale => Connection != ConnectionState.Connected;
}
