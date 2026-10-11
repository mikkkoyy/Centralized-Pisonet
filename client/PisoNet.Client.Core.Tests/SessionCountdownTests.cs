namespace PisoNet.Client.Core.Tests;

public class SessionCountdownTests
{
    [Fact]
    public void FreshCountdownHasNoValue()
    {
        var countdown = new SessionCountdown();
        Assert.False(countdown.HasValue);
        Assert.Equal(0, countdown.Current);
    }

    [Fact]
    public void SynchronizedValueCountsDownWithoutGoingNegative()
    {
        var countdown = new SessionCountdown();
        countdown.Synchronize(30);

        Assert.True(countdown.HasValue);
        Assert.InRange(countdown.Current, 29, 30);

        countdown.Synchronize(0);
        Assert.Equal(0, countdown.Current);
    }

    [Fact]
    public void ResetClearsTheAnchor()
    {
        var countdown = new SessionCountdown();
        countdown.Synchronize(30);
        countdown.Reset();

        Assert.False(countdown.HasValue);
        Assert.Equal(0, countdown.Current);
    }

    [Fact]
    public void ResynchronizationReplacesAnchorInsteadOfAccumulating()
    {
        var countdown = new SessionCountdown();
        countdown.Synchronize(600);
        countdown.Synchronize(10);

        // The second server value must win, not be added.
        Assert.InRange(countdown.Current, 9, 10);
    }

    [Fact]
    public void SynchronizeClampsNegativeServerValues()
    {
        var countdown = new SessionCountdown();
        countdown.Synchronize(-5);
        Assert.Equal(0, countdown.Current);
    }
}
