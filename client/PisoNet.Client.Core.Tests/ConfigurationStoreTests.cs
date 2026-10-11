namespace PisoNet.Client.Core.Tests;

public class ConfigurationStoreTests : IDisposable
{
    private readonly string _tempDirectory =
        Path.Combine(Path.GetTempPath(), Path.GetRandomFileName());

    public ConfigurationStoreTests()
    {
        Directory.CreateDirectory(_tempDirectory);
    }

    public void Dispose() => Directory.Delete(_tempDirectory, recursive: true);

    private string FilePath => Path.Combine(_tempDirectory, "config.json");

    [Fact]
    public void LoadReturnsNullWhenFileMissing()
    {
        var store = new ConfigurationStore(FilePath);
        Assert.Null(store.Load());
    }

    [Fact]
    public void SaveThenLoadRoundTripsAllFields()
    {
        var store = new ConfigurationStore(FilePath);
        var configuration = new ClientConfiguration
        {
            ServerUrl = "http://10.0.0.5:8000",
            StationCode = "PISO-07",
            DisplayName = "Counter 7",
            HeartbeatInterval = TimeSpan.FromSeconds(15),
            HttpTimeout = TimeSpan.FromSeconds(20),
        };

        store.Save(configuration);
        var loaded = store.Load();

        Assert.NotNull(loaded);
        Assert.Equal(configuration.ServerUrl, loaded!.ServerUrl);
        Assert.Equal(configuration.StationCode, loaded.StationCode);
        Assert.Equal(configuration.DisplayName, loaded.DisplayName);
        Assert.Equal(configuration.HeartbeatInterval, loaded.HeartbeatInterval);
        Assert.Equal(configuration.HttpTimeout, loaded.HttpTimeout);
    }

    [Fact]
    public void LoadFallsBackToDefaultsForUnsetIntervals()
    {
        var store = new ConfigurationStore(FilePath);
        store.Save(new ClientConfiguration
        {
            ServerUrl = "http://10.0.0.5:8000",
            StationCode = "PISO-07",
        });

        // Zero out the DTO values by rewriting the file directly.
        var dto = System.Text.Json.JsonSerializer.Serialize(new
        {
            ServerUrl = "http://10.0.0.5:8000",
            StationCode = "PISO-07",
            HeartbeatIntervalSeconds = 0,
            HttpTimeoutSeconds = 0,
        });
        File.WriteAllText(FilePath, dto);

        var loaded = store.Load();
        Assert.NotNull(loaded);
        Assert.Equal(ClientConfiguration.DefaultHeartbeatInterval, loaded!.HeartbeatInterval);
        Assert.Equal(ClientConfiguration.DefaultHttpTimeout, loaded.HttpTimeout);
    }

    [Fact]
    public void LoadReturnsNullForGarbageContent()
    {
        File.WriteAllText(FilePath, "definitely not json");
        var store = new ConfigurationStore(FilePath);
        Assert.Null(store.Load());
    }

    [Fact]
    public void LoadReturnsNullForMissingRequiredFields()
    {
        File.WriteAllText(FilePath, "{\"DisplayName\":\"x\"}");
        var store = new ConfigurationStore(FilePath);
        Assert.Null(store.Load());
    }

    [Fact]
    public void ClearRemovesTheFile()
    {
        var store = new ConfigurationStore(FilePath);
        store.Save(new ClientConfiguration
        {
            ServerUrl = "http://10.0.0.5:8000",
            StationCode = "PISO-07",
        });

        store.Clear();

        Assert.False(File.Exists(FilePath));
        Assert.Null(store.Load());
    }
}
