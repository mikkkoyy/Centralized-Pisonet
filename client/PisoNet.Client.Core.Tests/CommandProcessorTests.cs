using System.Net;

namespace PisoNet.Client.Core.Tests;

public class CommandProcessorTests
{
    private static ClientConfiguration Configuration() => new()
    {
        ServerUrl = "http://127.0.0.1:8000",
        StationCode = "PISO-01",
    };

    private static PendingCommandDto Command(
        long id,
        string type,
        long serverTime,
        long? expiresAt = null) => new(
        id, type, null, expiresAt ?? serverTime + 300);

    private static StationApiClient ApiClient(
        out List<HttpRequestMessage> requests,
        HttpStatusCode ackStatus = HttpStatusCode.OK)
    {
        var handler = new ScriptedHandler((_, _) =>
            Task.FromResult(HttpResponses.Json(ackStatus,
                """{"acknowledged":true,"command_id":1}""")));
        requests = handler.Requests;
        return new StationApiClient(Configuration(), handler);
    }

    [Fact]
    public async Task LockCommandAppliesAndAcknowledges()
    {
        using var apiClient = ApiClient(out var requests);
        var state = new StationStateModel();
        var processor = new CommandProcessor(apiClient, state);
        const long serverTime = 1_700_000_000;

        await processor.ProcessAsync(
            new[] { Command(1, "lock", serverTime) }, serverTime);

        Assert.True(state.IsAdminLocked);
        var request = Assert.Single(requests);
        Assert.Contains("/commands/1/ack", request.RequestUri!.ToString());
    }

    [Fact]
    public async Task UnlockCommandClearsAdminLock()
    {
        using var apiClient = ApiClient(out _);
        var state = new StationStateModel { IsAdminLocked = true };
        var processor = new CommandProcessor(apiClient, state);
        const long serverTime = 1_700_000_000;

        await processor.ProcessAsync(
            new[] { Command(1, "unlock", serverTime) }, serverTime);

        Assert.False(state.IsAdminLocked);
    }

    [Fact]
    public async Task UnknownCommandTypeIsIgnoredWithoutAcknowledgement()
    {
        using var apiClient = ApiClient(out var requests);
        var state = new StationStateModel();
        var processor = new CommandProcessor(apiClient, state);
        const long serverTime = 1_700_000_000;

        await processor.ProcessAsync(
            new[] { Command(1, "shutdown", serverTime) }, serverTime);

        Assert.Empty(requests); // never executed, never acknowledged
        Assert.False(state.IsAdminLocked);
    }

    [Fact]
    public async Task ExpiredCommandIsNeverApplied()
    {
        using var apiClient = ApiClient(out var requests);
        var state = new StationStateModel();
        var processor = new CommandProcessor(apiClient, state);
        const long serverTime = 1_700_000_000;
        var expired = Command(1, "lock", serverTime,
            expiresAt: serverTime - 1);

        await processor.ProcessAsync(new[] { expired }, serverTime);

        Assert.Empty(requests);
        Assert.False(state.IsAdminLocked);
    }

    [Fact]
    public async Task CommandExpiresExactlyAtServerTimeIsExpired()
    {
        using var apiClient = ApiClient(out var requests);
        var state = new StationStateModel();
        var processor = new CommandProcessor(apiClient, state);
        const long serverTime = 1_700_000_000;
        var expiring = Command(1, "lock", serverTime,
            expiresAt: serverTime);

        await processor.ProcessAsync(new[] { expiring }, serverTime);

        Assert.Empty(requests);
    }

    [Fact]
    public async Task DuplicateDeliveryIsAppliedOnce()
    {
        using var apiClient = ApiClient(out var requests);
        var state = new StationStateModel();
        var processor = new CommandProcessor(apiClient, state);
        const long serverTime = 1_700_000_000;
        var command = new[] { Command(1, "lock", serverTime) };

        await processor.ProcessAsync(command, serverTime);
        await processor.ProcessAsync(command, serverTime);

        Assert.Single(requests); // idempotent: acknowledged once
        Assert.True(state.IsAdminLocked);
    }

    [Fact]
    public async Task AcknowledgementFailureLeavesCommandPending()
    {
        using var apiClient = ApiClient(out var requests, HttpStatusCode.InternalServerError);
        var state = new StationStateModel();
        var processor = new CommandProcessor(apiClient, state);
        const long serverTime = 1_700_000_000;
        var command = new[] { Command(1, "lock", serverTime) };

        await processor.ProcessAsync(command, serverTime);
        Assert.Single(requests);
        Assert.True(state.IsAdminLocked); // applied locally

        // Redelivery must attempt again (command was not
        // recorded as acknowledged).
        await processor.ProcessAsync(command, serverTime);
        Assert.Equal(2, requests.Count);
    }

    [Fact]
    public async Task AuthenticationFailureDuringAckSurfacesImmediately()
    {
        using var apiClient = ApiClient(out _, HttpStatusCode.Unauthorized);
        var state = new StationStateModel();
        var processor = new CommandProcessor(apiClient, state);
        const long serverTime = 1_700_000_000;

        // The command was applied locally but the credential
        // problem must propagate to the heartbeat service.
        await Assert.ThrowsAsync<StationAuthenticationException>(
            () => processor.ProcessAsync(
                new[] { Command(1, "lock", serverTime) }, serverTime));
    }
}
