namespace PisoNet.Client.Core.Tests;

/// <summary>
/// Records requests and returns scripted responses, so the
/// protocol client can be tested without a live server.
/// </summary>
internal sealed class ScriptedHandler : HttpMessageHandler
{
    private readonly Func<HttpRequestMessage, CancellationToken, Task<HttpResponseMessage>> _respond;

    public ScriptedHandler(
        Func<HttpRequestMessage, CancellationToken, Task<HttpResponseMessage>>? respond = null)
    {
        _respond = respond ?? ((_, _) =>
            Task.FromResult(new HttpResponseMessage(System.Net.HttpStatusCode.OK)));
    }

    public List<HttpRequestMessage> Requests { get; } = new();

    protected override Task<HttpResponseMessage> SendAsync(
        HttpRequestMessage request,
        CancellationToken cancellationToken)
    {
        Requests.Add(request);
        return _respond(request, cancellationToken);
    }
}

internal static class HttpResponses
{
    public static HttpResponseMessage Json(
        System.Net.HttpStatusCode statusCode,
        string body)
    {
        return new HttpResponseMessage(statusCode)
        {
            Content = new StringContent(body, System.Text.Encoding.UTF8, "application/json"),
        };
    }
}
