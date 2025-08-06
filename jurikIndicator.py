import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

def calculate_jma(source: pd.Series, length: int = 7, phase: int = 50, power: int = 2) -> pd.Series:
    """
    Converts the PineScript Jurik Moving Average (JMA) indicator to Python.

    :param source: pd.Series of source prices (e.g., 'close' prices).
    :param length: The length of the JMA.
    :param phase: The phase of the JMA, controlling overshoot/undershoot.
                   Ranges from -100 to 100.
    :param power: The power used in the calculation, affecting smoothness.
    :return: pd.Series containing the JMA values.
    """
    
    # --- 1. Parameter Calculations ---
    # These are calculated once at the beginning.
    
    # phaseRatio calculation
    if phase < -100:
        phase_ratio = 0.5
    elif phase > 100:
        phase_ratio = 2.5
    else:
        phase_ratio = phase / 100 + 1.5

    # beta calculation
    beta = 0.45 * (length - 1) / (0.45 * (length - 1) + 2)
    
    # alpha calculation
    alpha = beta ** power

    # --- 2. JMA Calculation ---
    # We need to iterate through the source data to calculate the JMA step-by-step
    # because each value depends on the previous one.
    
    # Initialize series for storing intermediate and final values
    jma_series = pd.Series(index=source.index, dtype=float)
    
    # Initialize state variables. In PineScript, these are implicitly initialized.
    # nz(e0[1]) means use the previous value of e0, or 0 if it doesn't exist.
    prev_e0 = 0.0
    prev_e1 = 0.0
    prev_e2 = 0.0
    prev_jma = 0.0

    # Loop through each price point in the source series
    for i in range(len(source)):
        price = source.iloc[i]

        # In PineScript, during the first bar, nz(variable[1]) returns 0.
        # Our initial `prev_` values are already 0.0, simulating this.
        # After the first bar, we update `prev_` variables with the calculated values.
        if i == 0:
            # On the first bar, JMA is just the source price
            e0 = price
            e1 = 0.0
            e2 = 0.0
            jma = price
        else:
            e0 = (1 - alpha) * price + alpha * prev_e0
            e1 = (price - e0) * (1 - beta) + beta * prev_e1
            e2 = (e0 + phase_ratio * e1 - prev_jma) * ((1 - alpha) ** 2) + (alpha ** 2) * prev_e2
            jma = e2 + prev_jma
        
        jma_series.iloc[i] = jma

        # Update the 'previous' state variables for the next iteration
        prev_e0 = e0
        prev_e1 = e1
        prev_e2 = e2
        prev_jma = jma
        
    jma_series.name = f"JMA_{length}_{phase}_{power}"
    return jma_series


# --- 3. Example Usage & Plotting ---

if __name__ == '__main__':
    # Create some sample price data
    data = {
        'open': np.random.uniform(95, 105, 200),
        'high': np.random.uniform(100, 110, 200),
        'low': np.random.uniform(90, 100, 200),
        'close': 100 + np.sin(np.linspace(0, 20, 200)) * 5 + np.random.randn(200) * 0.5
    }
    df = pd.DataFrame(data)
    df['high'] = df[['open', 'close']].max(axis=1) + np.random.uniform(0, 2, 200)
    df['low'] = df[['open', 'close']].min(axis=1) - np.random.uniform(0, 2, 200)

    # --- Calculate the JMA ---
    # Using the default values from the PineScript (length=7, phase=50)
    jma_values = calculate_jma(df['close'], length=7, phase=50, power=2)

    # Add the JMA to the DataFrame
    df['jma'] = jma_values
    
    print("DataFrame with JMA:")
    print(df.tail())

    # --- Plotting ---
    # This section replicates the `plot()` and `highlightMovements` functionality
    

    # Determine the color based on movement (up or down) and highlight the movements
    highlight_movements = True
    
    if highlight_movements:
        # Create separate series for up and down movements for clean plotting
        df['jma_up'] = np.where(df['jma'] > df['jma'].shift(1), df['jma'], np.nan)
        df['jma_down'] = np.where(df['jma'] < df['jma'].shift(1), df['jma'], np.nan)
        # Handle the first point, when we are plotting JMA movement
        df['jma_up'].iloc[0] = df['jma'].iloc[0] if df['jma'].iloc[1] > df['jma'].iloc[0] else np.nan
        df['jma_down'].iloc[0] = df['jma'].iloc[0] if df['jma'].iloc[1] < df['jma'].iloc[0] else np.nan
        
        plt.figure(figsize=(14, 7))
        plt.plot(df['close'], label='Close Price', color='gray', alpha=0.8)
        
        # Plot up and down JMA lines with different colors
        plt.plot(df['jma_up'], label='JMA (Up)', color='green', linewidth=2)
        plt.plot(df['jma_down'], label='JMA (Down)', color='red', linewidth=2)
        
        plt.title('Jurik Moving Average (JMA) with Movement Highlighting')
        
    else:
        # Plot with a single color
        plt.figure(figsize=(14, 7))
        plt.plot(df['close'], label='Close Price', color='gray', alpha=0.8)
        plt.plot(df['jma'], label='JMA', color='#6d1e7f', linewidth=2) # Original purple color
        plt.title('Jurik Moving Average (JMA)')

    plt.legend()
    plt.grid(True)
    plt.show()