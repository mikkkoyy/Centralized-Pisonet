using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace PisoNet.Client.Core;

/// <summary>
/// Stores station credentials in a per-user file protected with Windows
/// DPAPI (CurrentUser scope). Only the Windows user account that encrypted
/// the file can decrypt it; the token is never stored in plaintext and
/// never written to logs.
/// </summary>
public sealed class DpapiCredentialStore : ICredentialStore
{
    // App-identifying entropy. Not a secret: DPAPI provides the actual
    // protection; entropy only prevents cross-application decryption.
    private static readonly byte[] Entropy = Encoding.UTF8.GetBytes("MKY-PisoNet-Station-Client/v1");

    private readonly string _filePath;

    /// <summary>Creates a store, optionally at a custom path.</summary>
    /// <param name="filePath">Credential file path; defaults to <see cref="AppPaths.CredentialFilePath"/>.</param>
    public DpapiCredentialStore(string? filePath = null)
    {
        _filePath = filePath ?? AppPaths.CredentialFilePath;
    }

    /// <summary>Loads stored credentials, or returns false when none exist (or they cannot be decrypted).</summary>
    /// <param name="credentials">Loaded credentials when true is returned.</param>
    public bool TryLoad(out StationCredentials? credentials)
    {
        credentials = null;
        if (!File.Exists(_filePath))
        {
            return false;
        }

        try
        {
            var cipherText = Convert.FromBase64String(File.ReadAllText(_filePath));
            var plainText = ProtectedData.Unprotect(cipherText, Entropy, DataProtectionScope.CurrentUser);
            var dto = JsonSerializer.Deserialize<CredentialDto>(Encoding.UTF8.GetString(plainText));
            if (dto is null || string.IsNullOrEmpty(dto.StationCode) || string.IsNullOrEmpty(dto.Token))
            {
                return false;
            }

            credentials = new StationCredentials(dto.StationCode, dto.Token);
            return true;
        }
        catch (CryptographicException)
        {
            // Tampered, corrupt, or encrypted for a different user/machine.
            return false;
        }
        catch (FormatException)
        {
            return false;
        }
        catch (JsonException)
        {
            return false;
        }
        catch (InvalidOperationException)
        {
            return false;
        }
    }

    /// <summary>Persists credentials using DPAPI-protected storage.</summary>
    /// <param name="credentials">Credentials to store.</param>
    public void Save(StationCredentials credentials)
    {
        ArgumentNullException.ThrowIfNull(credentials);

        var dto = new CredentialDto(credentials.StationCode, credentials.Token);
        var plainText = Encoding.UTF8.GetBytes(JsonSerializer.Serialize(dto));
        var cipherText = ProtectedData.Protect(plainText, Entropy, DataProtectionScope.CurrentUser);

        var directory = Path.GetDirectoryName(_filePath);
        if (!string.IsNullOrEmpty(directory))
        {
            Directory.CreateDirectory(directory);
        }
        File.WriteAllText(_filePath, Convert.ToBase64String(cipherText));
    }

    /// <summary>Deletes the credential file.</summary>
    public void Clear()
    {
        if (File.Exists(_filePath))
        {
            File.Delete(_filePath);
        }
    }

    private sealed record CredentialDto(string StationCode, string Token);
}
