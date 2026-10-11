using System.ComponentModel;

namespace PisoNet.Client.WinForms;

/// <summary>Circular connection/status indicator dot.</summary>
internal sealed class StatusDot : Control
{
    private Color _dotColor = UiTheme.Muted;

    [Browsable(false)]
    [DesignerSerializationVisibility(DesignerSerializationVisibility.Hidden)]
    public Color DotColor
    {
        get => _dotColor;
        set
        {
            _dotColor = value;
            Invalidate();
        }
    }

    public StatusDot()
    {
        Size = new Size(12, 12);
        DoubleBuffered = true;
    }

    protected override void OnPaint(PaintEventArgs e)
    {
        e.Graphics.SmoothingMode = System.Drawing.Drawing2D.SmoothingMode.AntiAlias;
        using var brush = new SolidBrush(_dotColor);
        e.Graphics.FillEllipse(brush, 0, 0, Width - 1, Height - 1);
    }
}
