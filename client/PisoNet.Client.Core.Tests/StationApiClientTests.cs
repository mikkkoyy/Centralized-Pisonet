using System.Net;
using System.Text;
using System.Text.Json;

namespace PisoNet.Client.Core.Tests;

public class StationApiClientTests
{
    private static ClientConfiguration Configuration() => new()
    {
        ServerUrl = "http://127.0.0.1:8000",
        StationCode = "PISO-01",
    };

    [Fact]
    public async Task RegisterSendsVersionHeaderAndCorrectPayload()
    {
        var handler = new ScriptedHandler((_, _) =>
            Task.FromResult(HttpResponses.Json(HttpStatusCode.Created,
                """{"station_id":7,"station_code":"PISO-01","token":"tok","protocol_version":1,"enrolled_at":1700000000}""")));
        using var client = new StationApiClient(Configuration(), handler);

        var response = await client.RegisterAsync("enroll-secret");

        Assert.Equal(7, response.StationId);
        Assert.Equal("tok", response.Token);

        var request = Assert.Single(handler.Requests);
        Assert.Contains("api/v1/stations/register", request.RequestUri!.ToString());
        Assert.Equal("1", request.Headers.GetValues("X-Api-Version").Single());
        Assert.DoesNotContain("Authorization", request.Headers.ToString());

        var body = JsonSerializer.Deserialize<JsonElement>(
            await request.Content!.ReadAsStringAsync());
        Assert.Equal("PISO-01", body.GetProperty("station_code").GetString());
        Assert.Equal("enroll-secret", body.GetProperty("enrollment_secret").GetString());
        Assert.Equal(JsonValueKind.Null, body.GetProperty("mac_address").ValueKind);
    }

    [Fact]
    public async Task HeartbeatSendsBearerTokenAndVersionHeader()
    {
        var handler = new ScriptedHandler((_, _) =>
            Task.FromResult(HttpResponses.Json(HttpStatusCode.OK,
                """{"station_code":"PISO-01","protocol_version":1,"server_time":1700000000,"station_state":"available","lock":"locked","session":null,"commands":null}""")));
        using var client = new StationApiClient(Configuration(), handler);
        client.SetStationToken("tok");

        await client.HeartbeatAsync();

        var request = Assert.Single(handler.Requests);
        Assert.Equal("1", request.Headers.GetValues("X-Api-Version").Single());
        Assert.Equal("Bearer tok", request.Headers.GetValues("Authorization").Single());
        Assert.Contains("api/v1/stations/PISO-01/heartbeat",
            request.RequestUri!.ToString());
    }

    [Fact]
    public async Task AcknowledgeTargetsCommandAckEndpoint()
    {
        var handler = new ScriptedHandler((_, _) =>
            Task.FromResult(HttpResponses.Json(HttpStatusCode.OK,
                """{"acknowledged":true,"command_id":42}""")));
        using var client = new StationApiClient(Configuration(), handler);

        var response = await client.AcknowledgeCommandAsync(42);

        Assert.True(response.Acknowledged);
        var request = Assert.Single(handler.Requests);
        Assert.Contains("api/v1/stations/PISO-01/commands/42/ack",
            request.RequestUri!.ToString());
        Assert.Equal("1", request.Headers.GetValues("X-Api-Version").Single());
    }

    [Fact]
    public async Task HeartbeatRejectsMissingVersionHeaderServerSide_400()
    {
        var handler = new ScriptedHandler((_, _) =>
            Task.FromResult(HttpResponses.Json(HttpStatusCode.BadRequest,
                """{"detail":"X-Api-Version header is required"}""")));
        using var client = new StationApiClient(Configuration(), handler);

        var exception = await Assert.ThrowsAsync<ProtocolVersionMismatchException>(
            () => client.HeartbeatAsync());
        Assert.Equal(400, exception.StatusCode);
        Assert.Contains("X-Api-Version", exception.Message);
    }

    [Fact]
    public async Task UnauthorizedMapsToAuthenticationException()
    {
        var handler = new ScriptedHandler((_, _) =>
            Task.FromResult(HttpResponses.Json(HttpStatusCode.Unauthorized,
                """{"detail":"invalid or revoked token"}""")));
        using var client = new StationApiClient(Configuration(), handler);

        var exception = await Assert.ThrowsAsync<StationAuthenticationException>(
            () => client.HeartbeatAsync());
        Assert.Equal(401, exception.StatusCode);
        Assert.Contains("invalid or revoked token", exception.Message);
    }

    [Fact]
    public async Task ForbiddenMapsToEnrollmentRejectedException()
    {
        var handler = new ScriptedHandler((_, _) =>
            Task.FromResult(HttpResponses.Json(HttpStatusCode.Forbidden,
                """{"detail":"invalid enrollment secret"}""")));
        using var client = new StationApiClient(Configuration(), handler);

        var exception = await Assert.ThrowsAsync<EnrollmentRejectedException>(
            () => client.RegisterAsync("bad-secret"));
        Assert.Equal(403, exception.StatusCode);
    }

    [Fact]
    public async Task ConflictMapsToDuplicateStationException()
    {
        var handler = new ScriptedHandler((_, _) =>
            Task.FromResult(HttpResponses.Json(HttpStatusCode.Conflict,
                """{"detail":"station code already registered"}""")));
        using var client = new StationApiClient(Configuration(), handler);

        var exception = await Assert.ThrowsAsync<DuplicateStationException>(
            () => client.RegisterAsync("secret"));
        Assert.Equal(409, exception.StatusCode);
    }

    [Fact]
    public async Task NotFoundMapsToProtocolException()
    {
        var handler = new ScriptedHandler((_, _) =>
            Task.FromResult(HttpResponses.Json(HttpStatusCode.NotFound,
                """{"detail":"no such command"}""")));
        using var client = new StationApiClient(Configuration(), handler);

        var exception = await Assert.ThrowsAsync<StationProtocolException>(
            () => client.AcknowledgeCommandAsync(999));
        Assert.Equal(404, exception.StatusCode);
        Assert.IsNotType<StationAuthenticationException>(exception);
    }

    [Fact]
    public async Task EmptySuccessBodyThrowsProtocolException()
    {
        var handler = new ScriptedHandler((_, _) =>
            Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)));
        using var client = new StationApiClient(Configuration(), handler);

        await Assert.ThrowsAsync<StationProtocolException>(
            () => client.HeartbeatAsync());
    }

    [Fact]
    public async Task ValidationErrorsSurfaceReadableDetailWithoutInput()
    {
        // FastAPI returns 422 with an array of validation
        // errors; the "input" member echoes the submitted
        // value and must never be surfaced (it may be the
        // enrollment secret).
        var handler = new ScriptedHandler((_, _) =>
            Task.FromResult(HttpResponses.Json(HttpStatusCode.UnprocessableEntity,
                """{"detail":[{"type":"value_error","loc":["body","enrollment_secret"],"msg":"String should have at least 16 characters","input":"secret-that-was-submitted"}]}""")));
        using var client = new StationApiClient(Configuration(), handler);

        var exception = await Assert.ThrowsAsync<StationProtocolException>(
            () => client.RegisterAsync("secret-that-was-submitted"));
        Assert.Equal(422, exception.StatusCode);
        Assert.Contains("enrollment_secret", exception.Message);
        Assert.Contains("at least 16 characters", exception.Message);
        Assert.DoesNotContain("secret-that-was-submitted", exception.Message);
    }

    [Fact]
    public async Task UnauthenticatedRequestsOmitBearerHeader()
    {
        var handler = new ScriptedHandler((_, _) =>
            Task.FromResult(HttpResponses.Json(HttpStatusCode.OK,
                """{"station_code":"PISO-01","protocol_version":1,"server_time":1,"station_state":"available","lock":"locked","session":null,"commands":null}""")));
        using var client = new StationApiClient(Configuration(), handler);

        await client.HeartbeatAsync();

        var request = Assert.Single(handler.Requests);
        Assert.False(request.Headers.Contains("Authorization"));
    }

    [Fact]
    public async Task EscapesStationCodeInUrls()
    {
        var handler = new ScriptedHandler((_, _) =>
            Task.FromResult(HttpResponses.Json(HttpStatusCode.OK,
                """{"station_code":"a b","protocol_version":1,"server_time":1,"station_state":"available","lock":"locked","session":null,"commands":null}""")));
        var configuration = Configuration() with { StationCode = "a b" };
        using var client = new StationApiClient(configuration, handler);

        await client.HeartbeatAsync();

        var request = Assert.Single(handler.Requests);
        Assert.Contains("a%20b", request.RequestUri!.GetComponents(
            UriComponents.SerializationInfoString, UriFormat.UriEscaped));
    }
}
