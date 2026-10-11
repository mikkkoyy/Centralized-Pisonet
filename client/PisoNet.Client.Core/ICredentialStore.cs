namespace PisoNet.Client.Core;

/// <summary>
/// Secure storage abstraction for station credentials. Implementations
/// must never persist the token in plaintext.
/// </summary>
public interface ICredentialStore
{
    /// <summary>Loads stored credentials, or returns false when none exist (or they cannot be decrypted).</summary>
    bool TryLoad(out StationCredentials? credentials);

    /// <summary>Persists credentials using protected storage.</summary>
    void Save(StationCredentials credentials);

    /// <summary>Removes stored credentials (used for reset and re-enrollment).</summary>
    void Clear();
}
