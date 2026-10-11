namespace PisoNet.Client.Core;

/// <summary>Session lifecycle as observed by the client.</summary>
public enum SessionStatus
{
    /// <summary>No active session.</summary>
    None,

    /// <summary>Active session with remaining paid time.</summary>
    Active,

    /// <summary>Session time elapsed (observed locally between synchronizations).</summary>
    Expired,

    /// <summary>
    /// The server reported the session ended (expired or terminated
    /// by an administrator). The protocol does not distinguish the
    /// two, so the client reports a single ended state.
    /// </summary>
    Terminated,
}
