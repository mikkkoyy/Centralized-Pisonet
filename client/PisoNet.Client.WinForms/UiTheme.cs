namespace PisoNet.Client.WinForms;

/// <summary>Shared dark theme palette and typography.</summary>
internal static class UiTheme
{
    public static readonly Color Background = Color.FromArgb(23, 24, 29);
    public static readonly Color Card = Color.FromArgb(32, 34, 42);
    public static readonly Color CardBorder = Color.FromArgb(52, 56, 68);
    public static readonly Color Text = Color.FromArgb(230, 232, 238);
    public static readonly Color Muted = Color.FromArgb(154, 160, 171);
    public static readonly Color Accent = Color.FromArgb(79, 143, 247);
    public static readonly Color Ok = Color.FromArgb(63, 185, 106);
    public static readonly Color Warn = Color.FromArgb(217, 161, 59);
    public static readonly Color Bad = Color.FromArgb(229, 83, 75);

    public static readonly Font TitleFont = new("Segoe UI", 10f, FontStyle.Bold);
    public static readonly Font StateFont = new("Segoe UI", 11f);
    public static readonly Font CountdownFont = new("Segoe UI", 34f, FontStyle.Regular);
    public static readonly Font StationCodeFont = new("Segoe UI", 16f, FontStyle.Bold);
    public static readonly Font MessageFont = new("Segoe UI", 9.5f);
}
