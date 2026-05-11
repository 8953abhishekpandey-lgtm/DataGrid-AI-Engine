"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  chart_utils.py  —  DataGrid Intelligence · Chart Generator               ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  Is file ka kaam hai DataFrame ko Plotly chart mein convert karna.         ║
║                                                                             ║
║  Do main functions hain:                                                   ║
║    1. generate_chart() — specific chart type ke saath chart banao          ║
║    2. auto_chart()     — DataFrame dekh ke automatically chart type choose ║
║                                                                             ║
║  Output: Plotly JSON string jo frontend JavaScript mein render hota hai    ║
║                                                                             ║
║  Supported Chart Types:                                                    ║
║    bar | line | area | pie | scatter | histogram | heatmap                 ║
║                                                                             ║
║  Agar chart nahi ban sakta (empty data, error) toh '' (empty string)       ║
║  return hoti hai — caller code check karta hai aur gracefully handle karta ║
╚══════════════════════════════════════════════════════════════════════════════╝

IMPORTANT NOTES:
  - Plotly JSON frontend pe Plotly.js se render hota hai
  - Transparent background use karta hai taaki UI theme se match kare
  - Color scheme consistent hai puri application mein (#0f7c90 = teal primary)
  - Sabhi errors silently handle hote hain — empty string return hoti hai
"""

import pandas as pd                    # DataFrame operations ke liye
import plotly.express as px            # High-level chart API (easy use)
import plotly.graph_objects as go      # Low-level chart API (advanced control)
                                       # go yahan import hai future use ke liye


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1: CHART THEME CONFIGURATION
# Poori application mein consistent look-and-feel ke liye
# Ye dict fig.update_layout(**CHART_THEME) se apply hota hai
# ══════════════════════════════════════════════════════════════════════════════

CHART_THEME = dict(
    template      = "plotly_white",
    # ^ Plotly ka built-in white theme use karo
    # Alternatives: "plotly_dark", "ggplot2", "seaborn", "simple_white"

    paper_bgcolor = "rgba(0,0,0,0)",
    # ^ Chart ke outer area ka background TRANSPARENT rakho
    # rgba(0,0,0,0) = Red=0, Green=0, Blue=0, Alpha=0 (fully transparent)
    # Isse chart page ke background color se match karta hai

    plot_bgcolor  = "#f8fafc",
    # ^ Chart ke inner plot area ka background color (light gray-blue)
    # #f8fafc = Tailwind CSS ka "slate-50" color — subtle aur clean

    font          = dict(
        color  = "#162033",     # Font color: dark navy blue (readable)
        size   = 12,            # Base font size: 12px
        family = "Inter, Segoe UI, sans-serif",
        # ^ Font family priority:
        #   1. Inter (modern, clean)
        #   2. Segoe UI (Windows default)
        #   3. sans-serif (fallback)
    ),

    margin = dict(
        l = 52,   # Left margin: 52px (axis labels ke liye space)
        r = 22,   # Right margin: 22px (minimal)
        t = 52,   # Top margin: 52px (title ke liye space)
        b = 48,   # Bottom margin: 48px (x-axis labels ke liye space)
    ),

    colorway = [
        "#0f7c90",   # Primary: Teal/Cyan (DataGrid brand color)
        "#f5a623",   # Secondary: Orange/Amber
        "#248a52",   # Tertiary: Green
        "#6b5bd3",   # Quaternary: Purple
        "#c2413d",   # Quinary: Red
        "#4f8bd6",   # Senary: Blue
    ],
    # ^ Jab multiple data series hon toh ye colors order mein use hote hain
    # Example: Multi-line chart mein line 1 = teal, line 2 = orange, etc.
)


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2: MAIN CHART GENERATOR
# Specific chart type ke saath Plotly figure banata hai
# ══════════════════════════════════════════════════════════════════════════════

def generate_chart(df: pd.DataFrame, chart_type: str, title: str = "") -> str:
    """
    DataFrame se specified type ka Plotly chart banata hai.

    Args:
        df         : pandas DataFrame jisme data hai
        chart_type : chart type string ("bar", "line", "pie", etc.)
        title      : chart ka title (optional, default empty)

    Returns:
        str: Plotly JSON string (frontend pe render hoga)
             Ya '' (empty string) agar chart nahi ban saka

    Column Detection Logic:
        - date_cols  = datetime columns (x-axis ke liye prefer)
        - cat_cols   = categorical/text columns (x-axis fallback)
        - num_cols   = numeric columns (y-axis ke liye)
        - x_col      = best x-axis column: datetime > categorical > first col
        - y_col      = best y-axis column: first numeric > second col
    """
    if df.empty:
        return ""                       # Empty DataFrame pe koi chart nahi banta

    # ── Column type detection ──────────────────────────────────────────────────
    cols = df.columns.tolist()          # Saare column names ki list

    num_cols = [
        c for c in cols
        if pd.api.types.is_numeric_dtype(df[c])    # Integer ya float type check
    ]
    # ^ Numeric columns: SUM, AVG, COUNT wagera ke liye y-axis pe use honge

    cat_cols = [
        c for c in cols
        if not pd.api.types.is_numeric_dtype(df[c])  # Non-numeric = categorical
    ]
    # ^ Categorical columns: Status, District, Meter_Type wagera x-axis pe jayenge

    date_cols = [
        c for c in cols
        if pd.api.types.is_datetime64_any_dtype(df[c])  # datetime64 type check
    ]
    # ^ Date/time columns: time series charts ke liye prefer karo

    # ── Best axis columns choose karo ──────────────────────────────────────────
    x_col = (
        date_cols[0] if date_cols   # Pehle datetime column prefer karo
        else cat_cols[0] if cat_cols  # Phir categorical column
        else cols[0]                 # Fallback: jo bhi pehla column ho
    )
    # ^ x_col = x-axis pe kaunsa column dikhana hai

    y_col = (
        num_cols[0] if num_cols      # Numeric column prefer karo y-axis ke liye
        else (cols[1] if len(cols) > 1 else cols[0])  # Fallback: doosra column
    )
    # ^ y_col = y-axis pe kaunsa column dikhana hai

    # ── Chart type normalize karo ──────────────────────────────────────────────
    ct = (chart_type or "bar").lower().strip()
    # .lower() = case-insensitive comparison ke liye
    # .strip() = extra spaces remove karo
    # or "bar" = agar None ya empty string hai toh default "bar"

    # ── Chart banao try block mein ──────────────────────────────────────────────
    try:

        # ── BAR CHART ────────────────────────────────────────────────────────────
        if ct == "bar":
            fig = px.bar(
                df,                           # Data source: DataFrame
                x     = x_col,               # X-axis: categorical/date column
                y     = y_col,               # Y-axis: numeric column
                title = title,               # Chart title
                color_discrete_sequence = ["#0f7c90"],  # Primary teal color
            )
            # px.bar() = bar chart banata hai
            # Bar charts best hain: comparisons, rankings, counts ke liye

        # ── LINE CHART ───────────────────────────────────────────────────────────
        elif ct == "line":
            fig = px.line(
                df,
                x       = x_col,
                y       = y_col,
                title   = title,
                markers = True,              # Har data point pe dot dikhao
                color_discrete_sequence = ["#0f7c90"],
            )
            # px.line() = line chart
            # markers=True = line ke saath circles bhi dikhenge
            # Best for: time series, trends, continuous data

        # ── AREA CHART ───────────────────────────────────────────────────────────
        elif ct == "area":
            fig = px.area(
                df,
                x     = x_col,
                y     = y_col,
                title = title,
                color_discrete_sequence = ["#0f7c90"],
            )
            # px.area() = filled area chart (line ke neeche fill hota hai)
            # Best for: cumulative values, volume over time

        # ── PIE CHART ────────────────────────────────────────────────────────────
        elif ct == "pie":
            v = (
                num_cols[0]              # Numeric column as values (slice sizes)
                if num_cols
                else (cols[1] if len(cols) > 1 else cols[0])  # Fallback
            )
            fig = px.pie(
                df,
                names  = x_col,          # Slice labels: categorical column
                values = v,              # Slice sizes: numeric column
                title  = title,
            )
            # px.pie() = pie/donut chart
            # names = slice ka label, values = slice ka size
            # Best for: percentage breakdown, proportions (max 6-8 categories)

        # ── SCATTER CHART ────────────────────────────────────────────────────────
        elif ct == "scatter":
            x2 = (
                num_cols[0]              # X-axis: pehla numeric column
                if num_cols
                else x_col               # Fallback: detected x_col
            )
            y2 = (
                num_cols[1]              # Y-axis: doosra numeric column (different se)
                if len(num_cols) > 1
                else (num_cols[0] if num_cols else y_col)  # Fallback
            )
            fig = px.scatter(
                df,
                x     = x2,
                y     = y2,
                title = title,
                color_discrete_sequence = ["#0f7c90"],
            )
            # px.scatter() = scatter plot / dot chart
            # Best for: correlations, distributions, outlier detection
            # Example: GPS_LAT vs GPS_LONG = meter locations map jaisa

        # ── HISTOGRAM ────────────────────────────────────────────────────────────
        elif ct == "histogram":
            fig = px.histogram(
                df,
                x      = y_col,          # Distribution of this column
                title  = title,
                nbins  = 30,             # 30 bins (buckets)
                color_discrete_sequence = ["#0f7c90"],
            )
            # px.histogram() = frequency distribution chart
            # nbins = kitne buckets mein data divide karo
            # Best for: data distribution, frequency analysis
            # Example: Meter count per area, readings distribution

        # ── HEATMAP ──────────────────────────────────────────────────────────────
        elif ct == "heatmap":
            if len(cols) >= 3:
                # Pivot table banao: 2 categorical columns × 1 numeric value
                pivot = df.pivot_table(
                    index   = cols[0],           # Rows: pehla column
                    columns = cols[1],           # Columns: doosra column
                    values  = y_col,             # Cell values: numeric column
                    aggfunc = "mean",            # Multiple values → average lo
                )
                # pivot_table() = spreadsheet-style pivot banata hai
                # aggfunc="mean" = agar ek cell mein multiple values hain toh average

                fig = px.imshow(
                    pivot,
                    title              = title,
                    color_continuous_scale = "Blues",  # Blue color gradient
                )
                # px.imshow() = 2D grid ko colored image ke roop mein dikhata hai
                # Blues scale: low values = light blue, high values = dark blue
            else:
                # Kam columns hain toh bar chart fallback
                fig = px.bar(df, x=x_col, y=y_col, title=title)

        # ── DEFAULT / UNKNOWN CHART TYPE ─────────────────────────────────────────
        else:
            # chart_type kuch bhi aaya jo recognized nahi hua
            if num_cols and cat_cols:
                # Numeric aur categorical dono hain: bar chart best hai
                fig = px.bar(
                    df,
                    x     = x_col,
                    y     = y_col,
                    title = title,
                    color_discrete_sequence = ["#0f7c90"],
                )
            elif len(num_cols) >= 2:
                # Sirf numeric columns hain: scatter plot dikhao
                fig = px.scatter(
                    df,
                    x     = num_cols[0],     # X: pehla numeric
                    y     = num_cols[1],     # Y: doosra numeric
                    title = title,
                    color_discrete_sequence = ["#0f7c90"],
                )
            else:
                # Kuch bhi proper nahi: simple bar chart as final fallback
                fig = px.bar(df, x=x_col, y=y_col, title=title)

        # ── Theme apply karo ───────────────────────────────────────────────────
        fig.update_layout(**CHART_THEME)
        # ** (double asterisk) = dictionary ko keyword arguments mein unpack karo
        # CHART_THEME se saari styling ek baar mein apply ho jaati hai

        return fig.to_json()
        # .to_json() = Plotly figure ko JSON string mein convert karo
        # Ye JSON frontend pe Plotly.js.parse() se render hota hai

    except Exception as e:
        # Koi bhi error aaye (column mismatch, empty data, etc.)
        print(f"  [chart] error ({ct}): {e}")
        # Error message print karo debugging ke liye
        return ""
        # Empty string return karo — caller isko "no chart" samjhega


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3: AUTO CHART SELECTOR
# DataFrame structure dekh ke khud decide karta hai kaunsa chart type best hai
# ══════════════════════════════════════════════════════════════════════════════

def auto_chart(df: pd.DataFrame, title: str = "") -> str:
    """
    DataFrame ka structure analyze karke automatically best chart type select karta hai
    aur chart JSON return karta hai.

    Decision Logic:
        - Empty DataFrame     → '' return karo
        - Numeric + Categorical columns hain AND 1 < rows ≤ 500 → bar chart
        - Baaki cases         → '' return karo (table mode)

    Args:
        df    : pandas DataFrame
        title : chart title (optional)

    Returns:
        str: Plotly JSON string ya '' (agar chartable nahi)

    Note:
        500 rows limit kyun? Zyada rows wale bar charts cluttered ho jaate hain.
        Large datasets ke liye user explicitly chart type specify kare.
    """
    if df.empty:
        return ""                       # Koi data nahi = koi chart nahi

    # Column types detect karo
    num_c = [
        c for c in df.columns
        if pd.api.types.is_numeric_dtype(df[c])       # Numeric columns list
    ]
    cat_c = [
        c for c in df.columns
        if not pd.api.types.is_numeric_dtype(df[c])   # Categorical columns list
    ]

    # Auto-chart decide karo
    if num_c and cat_c and 1 < len(df) <= 500:
        # Conditions:
        #   num_c  → koi numeric column hai (y-axis ke liye)
        #   cat_c  → koi categorical column hai (x-axis labels ke liye)
        #   1 < len(df) <= 500 → data meaningful size mein hai (too much nahi)
        return generate_chart(df, "bar", title)
        # Bar chart generate karo with auto-detected columns

    return ""
    # Conditions meet nahi huein: caller ko table mode mein dikhana chahiye