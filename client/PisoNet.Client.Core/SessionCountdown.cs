using System.Diagnostics;

namespace PisoNet.Client.Core;

/// <summary>
/// Animates remaining session time between server synchronizations.
/// The server value is authoritative; this class only interpolates
/// locally and resynchronizes on every successful heartbeat. It never
/// adds time: synchronization always replaces the anchor.
/// </summary>
public sealed class SessionCountdown
{
    private readonly Stopwatch _stopwatch = Stopwatch.StartNew();
    private int _anchoredRemainingSeconds;
    private long _anchoredElapsedTicks;
    private bool _hasAnchor;

    /// <summary>Resynchronizes with the server-authoritative remaining time.</summary>
    public void Synchronize(int remainingSeconds)
    {
        _anchoredRemainingSeconds = Math.Max(0, remainingSeconds);
        _anchoredElapsedTicks = _stopwatch.ElapsedTicks;
        _hasAnchor = true;
    }

    /// <summary>Clears the anchor (no active session).</summary>
    public void Reset() => _hasAnchor = false;

    /// <summary>Animated remaining seconds, floored at zero.</summary>
    public int Current
    {
        get
        {
            if (!_hasAnchor)
            {
                return 0;
            }

            var elapsedSeconds = (int)((_stopwatch.ElapsedTicks - _anchoredElapsedTicks) / Stopwatch.Frequency);
            return Math.Max(0, _anchoredRemainingSeconds - elapsedSeconds);
        }
    }

    /// <summary>True when a server value is anchored.</summary>
    public bool HasValue => _hasAnchor;
}
