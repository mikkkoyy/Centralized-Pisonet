namespace PisoNet.Client.Core.Tests;

public class ClientConfigurationTests
{
    private static ClientConfiguration Valid() => new()
    {
        ServerUrl = "http://127.0.0.1:8000",
        StationCode = "PISO-01",
    };

    [Fact]
    public void ValidConfigurationHasNoErrors()
    {
        var configuration = Valid();
        Assert.Empty(configuration.Validate());
        Assert.True(configuration.IsValid);
    }

    [Theory]
    [InlineData("http://10.0.0.5:8000")]
    [InlineData("https://shop.example.com")]
    public void AcceptsAbsoluteHttpUrls(string url)
    {
        var configuration = Valid() with { ServerUrl = url };
        Assert.Empty(configuration.Validate());
    }

    [Theory]
    [InlineData("10.0.0.5:8000")]
    [InlineData("ftp://example.com")]
    [InlineData("not a url")]
    [InlineData("")]
    public void RejectsNonHttpAbsoluteUrls(string url)
    {
        var configuration = Valid() with { ServerUrl = url };
        Assert.Contains(configuration.Validate(),
            error => error.Contains("absolute http"));
    }

    [Theory]
    [InlineData("PISO-01")]
    [InlineData("a")]
    [InlineData("station_02")]
    [InlineData("STATION-99")]
    public void AcceptsValidStationCodes(string code)
    {
        var configuration = Valid() with { StationCode = code };
        Assert.Empty(configuration.Validate());
    }

    [Theory]
    [InlineData("")]
    [InlineData(" ")]
    [InlineData("-leading-dash")]
    [InlineData("_leading-underscore")]
    [InlineData("has space")]
    [InlineData("has/slash")]
    [InlineData("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")] // 33 chars
    public void RejectsInvalidStationCodes(string code)
    {
        var configuration = Valid() with { StationCode = code };
        Assert.Contains(configuration.Validate(),
            error => error.Contains("Station code"));
    }

    [Fact]
    public void RejectsHeartbeatOutsideRange()
    {
        var tooFast = Valid() with
        {
            HeartbeatInterval = TimeSpan.FromSeconds(4),
        };
        Assert.Contains(tooFast.Validate(),
            error => error.Contains("Heartbeat interval"));

        var tooSlow = Valid() with
        {
            HeartbeatInterval = TimeSpan.FromSeconds(61),
        };
        Assert.Contains(tooSlow.Validate(),
            error => error.Contains("Heartbeat interval"));
    }

    [Fact]
    public void RejectsHttpTimeoutOutsideRange()
    {
        var tooShort = Valid() with { HttpTimeout = TimeSpan.FromSeconds(0.5) };
        Assert.Contains(tooShort.Validate(),
            error => error.Contains("HTTP timeout"));

        var tooLong = Valid() with { HttpTimeout = TimeSpan.FromSeconds(121) };
        Assert.Contains(tooLong.Validate(),
            error => error.Contains("HTTP timeout"));
    }

    [Fact]
    public void DefaultsAreWithinServerTolerance()
    {
        // Server stale timeout is 30s; default interval must
        // leave at least two chances before staleness.
        Assert.True(ClientConfiguration.DefaultHeartbeatInterval
            < TimeSpan.FromSeconds(30) / 2);
    }
}
