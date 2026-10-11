namespace PisoNet.Client.Core.Tests;

public class DpapiCredentialStoreTests : IDisposable
{
    private readonly string _tempDirectory =
        Path.Combine(Path.GetTempPath(), Path.GetRandomFileName());

    public DpapiCredentialStoreTests()
    {
        Directory.CreateDirectory(_tempDirectory);
    }

    public void Dispose() => Directory.Delete(_tempDirectory, recursive: true);

    private string FilePath => Path.Combine(_tempDirectory, "station.credentials");

    [Fact]
    public void TryLoadReturnsFalseWhenFileMissing()
    {
        var store = new DpapiCredentialStore(FilePath);
        Assert.False(store.TryLoad(out var credentials));
        Assert.Null(credentials);
    }

    [Fact]
    public void SaveThenLoadRoundTripsCredentials()
    {
        var store = new DpapiCredentialStore(FilePath);
        store.Save(new StationCredentials("PISO-01", "tok_secret_value"));

        Assert.True(store.TryLoad(out var credentials));
        Assert.Equal("PISO-01", credentials!.StationCode);
        Assert.Equal("tok_secret_value", credentials.Token);
    }

    [Fact]
    public void SavedFileIsNotPlaintext()
    {
        var store = new DpapiCredentialStore(FilePath);
        store.Save(new StationCredentials("PISO-01", "tok_secret_value"));

        var raw = File.ReadAllText(FilePath);
        Assert.DoesNotContain("tok_secret_value", raw);
        Assert.DoesNotContain("PISO-01", raw);
    }

    [Fact]
    public void TryLoadReturnsFalseForTamperedContent()
    {
        var store = new DpapiCredentialStore(FilePath);
        store.Save(new StationCredentials("PISO-01", "tok_secret_value"));

        File.WriteAllText(FilePath, "AAAAnot-base64-ciphertext!!!");
        Assert.False(store.TryLoad(out _));
    }

    [Fact]
    public void TryLoadReturnsFalseForEmptyCiphertext()
    {
        File.WriteAllText(FilePath, string.Empty);
        var store = new DpapiCredentialStore(FilePath);
        Assert.False(store.TryLoad(out _));
    }

    [Fact]
    public void ClearRemovesTheFile()
    {
        var store = new DpapiCredentialStore(FilePath);
        store.Save(new StationCredentials("PISO-01", "tok_secret_value"));

        store.Clear();

        Assert.False(File.Exists(FilePath));
        Assert.False(store.TryLoad(out _));
    }
}
