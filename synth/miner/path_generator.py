"""
Step 10: 1000-path generator (validator-aware)
Generates Path[0] (deterministic) and Paths[1..999] (stochastic ensemble).
"""

import numpy as np
from typing import List
import bittensor as bt

# Default degrees of freedom for Student-t distributions
DEFAULT_DF = {
    # Crypto
    "BTC": 5,
    "ETH": 5,
    "SOL": 4,
    # XAU
    "XAU": 10,
    # Equities (use Gaussian or high-df Student-t)
    "SPYX": 30,  # High df = close to Gaussian
    "NVDAX": 20,
    "TSLAX": 20,
    "AAPLX": 30,
    "GOOGLX": 30,
}


def get_student_t_df(asset: str) -> float:
    """Get Student-t degrees of freedom for asset, checking tuning history first."""
    # Check if parameter was tuned (from governance)
    from synth.miner.parameter_governance import get_governance
    governance = get_governance()
    tuned_value = governance.get_current_parameter_value(asset, "df")
    
    # If tuned value exists, use it; otherwise use default
    if tuned_value is not None:
        return tuned_value
    
    return DEFAULT_DF.get(asset, 5.0)  # Default df=5


def is_equity_asset(asset: str) -> bool:
    """Check if asset is equity (use Gaussian instead of Student-t)."""
    from synth.miner.equity_market_hours import EQUITY_ASSETS
    return asset in EQUITY_ASSETS


def generate_path_0(start_price: float, steps: int) -> np.ndarray:
    """
    Generate Path[0] - deterministic, gap-safe.
    
    Path[0] is SPECIAL:
    - deterministic
    - no stochastic noise
    - represents conditional mean trajectory
    - used exclusively for gap scoring
    
    Currently: flat path (S[0,k] = S0 for all k)
    
    Args:
        start_price: Starting price S0
        steps: Number of steps (path will have steps+1 points)
    
    Returns:
        Path[0] as numpy array of length (steps+1)
    """
    path_length = steps + 1
    # Flat path: all values equal to start_price
    path = np.full(path_length, float(start_price), dtype=np.float64)
    
    return path


def generate_stochastic_paths(
    start_price: float,
    steps: int,
    sigma_step: float,
    asset: str,
    num_paths: int = 999,
) -> np.ndarray:
    """
    Generate Paths[1..999] - stochastic ensemble.
    
    Sample innovations:
    - Crypto/XAU: Student-t(df)
    - Equities: Gaussian or high-df Student-t (df >= 20)
    
    Per step:
        R = sigma_step * Z
        S_{k+1} = S_k * exp(R)
    
    Vectorized:
        - Sample Z as matrix (num_paths, steps)
        - Cumulative sum in log space
        - exp to prices
    
    Args:
        start_price: Starting price S0
        steps: Number of steps
        sigma_step: Volatility per step
        asset: Asset symbol
        num_paths: Number of stochastic paths (default 999)
    
    Returns:
        Array of shape (num_paths, steps+1) containing price paths
    """
    # Determine distribution type
    if is_equity_asset(asset):
        # Equities: Use Gaussian (or high-df Student-t)
        df = get_student_t_df(asset)
        if df >= 20:
            # Use Gaussian (Student-t with high df approximates Gaussian)
            # Sample from standard normal
            Z = np.random.standard_normal(size=(num_paths, steps))
        else:
            # Use Student-t
            Z = np.random.standard_t(df=df, size=(num_paths, steps))
    else:
        # Crypto/XAU: Use Student-t
        df = get_student_t_df(asset)
        Z = np.random.standard_t(df=df, size=(num_paths, steps))
    
    # Scale by sigma_step
    # R = sigma_step * Z
    R = sigma_step * Z
    
    # Cumulative sum in log space
    # log_returns_cumsum[k] = sum(R[0..k])
    log_returns_cumsum = np.cumsum(R, axis=1)
    
    # Add initial point (all zeros for k=0)
    log_returns_cumsum = np.concatenate(
        [np.zeros((num_paths, 1)), log_returns_cumsum],
        axis=1
    )
    
    # Convert to prices: S_k = S0 * exp(cumsum)
    # Broadcast start_price to all paths
    paths = start_price * np.exp(log_returns_cumsum)
    
    # Final safety: replace NaN/Inf, enforce > 0
    paths = np.nan_to_num(paths, nan=start_price, posinf=start_price, neginf=start_price)
    paths = np.maximum(paths, 1e-8)  # Ensure all > 0
    
    return paths


def round_to_8_significant_digits(num: float) -> float:
    """Round to 8 significant digits."""
    if num == 0:
        return 0.0
    from math import log10, floor
    magnitude = floor(log10(abs(num)))
    decimal_places = 8 - magnitude - 1
    return round(num, decimal_places)


def generate_all_paths(
    start_price: float,
    steps: int,
    sigma_step: float,
    asset: str,
    num_simulations: int = 1000,
) -> List[List[float]]:
    """
    Generate all 1000 paths (Path[0] + Paths[1..999]).
    
    Args:
        start_price: Starting price S0
        steps: Number of steps (path will have steps+1 points)
        sigma_step: Volatility per step
        asset: Asset symbol
        num_simulations: Total number of paths (must be 1000)
    
    Returns:
        List of 1000 paths, each of length (steps+1)
        Path[0] is deterministic, Paths[1..999] are stochastic
        All prices are rounded to 8 significant digits
    """
    if num_simulations != 1000:
        raise ValueError(f"num_simulations must be 1000, got {num_simulations}")
    
    # Generate Path[0] (deterministic)
    path_0 = generate_path_0(start_price, steps)
    
    # Generate Paths[1..999] (stochastic)
    stochastic_paths = generate_stochastic_paths(
        start_price=start_price,
        steps=steps,
        sigma_step=sigma_step,
        asset=asset,
        num_paths=999,
    )
    
    # Combine: Path[0] + Paths[1..999]
    all_paths = []
    
    # Path[0] - round all prices
    all_paths.append([round_to_8_significant_digits(float(p)) for p in path_0.tolist()])
    
    # Paths[1..999] - round all prices
    for i in range(999):
        rounded_path = [round_to_8_significant_digits(float(p)) for p in stochastic_paths[i].tolist()]
        all_paths.append(rounded_path)
    
    # Final validation
    assert len(all_paths) == 1000, f"Expected 1000 paths, got {len(all_paths)}"
    assert len(all_paths[0]) == steps + 1, f"Path[0] wrong length: {len(all_paths[0])}"
    
    return all_paths
