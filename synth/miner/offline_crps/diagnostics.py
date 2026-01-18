"""
Step 16: Diagnostics (outside CRPS code)
Computes coverage rates, CRPS by horizon, and rolling averages.
"""

from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import numpy as np
import pandas as pd
import bittensor as bt


def calculate_coverage(
    price_paths: np.ndarray,
    realized_price: float,
    quantiles: List[float] = [0.05, 0.50, 0.95],
) -> Dict[str, float]:
    """
    Calculate coverage rates for given quantiles.
    
    Args:
        price_paths: Array of simulated paths (1000, path_length)
        realized_price: Realized price at a given time point
        quantiles: Quantile levels to check (e.g., [0.05, 0.50, 0.95])
    
    Returns:
        Dict mapping quantile level to binary (1 if covered, 0 if not)
    """
    # Calculate quantiles across paths
    path_quantiles = np.quantile(price_paths, quantiles, axis=0)
    
    coverage = {}
    for q, q_value in zip(quantiles, path_quantiles):
        if q < 0.5:
            # Lower quantile: check if realized >= quantile
            coverage[f"{int(q*100)}%"] = 1.0 if realized_price >= q_value else 0.0
        else:
            # Upper quantile: check if realized <= quantile
            coverage[f"{int(q*100)}%"] = 1.0 if realized_price <= q_value else 0.0
    
    return coverage


def calculate_coverage_rates(
    crps_results: List[Dict[str, Any]],
    price_paths_dict: Dict[str, np.ndarray],
    realized_prices_dict: Dict[str, float],
) -> Dict[str, float]:
    """
    Calculate aggregate coverage rates across all predictions.
    
    Returns:
        Dict with coverage rates for 5%, 50%, 95%
    """
    coverage_counts = {"5%": 0, "50%": 0, "95%": 0}
    total_count = 0
    
    for result in crps_results:
        pred_id = result["prediction_id"]
        
        if pred_id not in price_paths_dict or pred_id not in realized_prices_dict:
            continue
        
        price_paths = price_paths_dict[pred_id]
        realized = realized_prices_dict[pred_id]
        
        # Calculate coverage at final time point
        if price_paths.shape[1] > 0:
            final_prices = price_paths[:, -1]  # All paths at final time
            realized_final = realized  # Assuming realized is final price
            
            coverage = calculate_coverage(
                final_prices.reshape(1, -1),  # Reshape for compatibility
                realized_final,
            )
            
            for quantile in ["5%", "50%", "95%"]:
                if quantile in coverage:
                    coverage_counts[quantile] += coverage[quantile]
            
            total_count += 1
    
    # Calculate rates
    coverage_rates = {}
    for quantile in coverage_counts:
        if total_count > 0:
            coverage_rates[quantile] = coverage_counts[quantile] / total_count
        else:
            coverage_rates[quantile] = 0.0
    
    return coverage_rates


def split_crps_by_horizon(
    crps_results: List[Dict[str, Any]],
) -> Dict[str, List[float]]:
    """
    Split CRPS by horizon buckets.
    
    Horizon buckets:
    - short: 1-5min
    - medium: 15-60min
    - long: 3h / abs
    
    Returns:
        Dict mapping horizon to list of CRPS values
    """
    horizons = {
        "short": [],  # 1-5min
        "medium": [],  # 15-60min
        "long": [],  # 3h / abs
    }
    
    for result in crps_results:
        detailed_crps = result.get("detailed_crps", [])
        
        for crps_entry in detailed_crps:
            interval = crps_entry.get("Interval", "")
            crps_value = crps_entry.get("CRPS", 0.0)
            
            # Skip totals
            if crps_entry.get("Increment") == "Total":
                continue
            
            # Categorize by interval
            if interval in ["1min", "2min", "5min"]:
                horizons["short"].append(crps_value)
            elif interval in ["15min", "30min", "60min"]:
                horizons["medium"].append(crps_value)
            elif interval in ["3hour", "24hour_abs", "60min_abs"]:
                horizons["long"].append(crps_value)
    
    return horizons


def calculate_horizon_statistics(
    horizons: Dict[str, List[float]],
) -> Dict[str, Dict[str, float]]:
    """
    Calculate statistics for each horizon bucket.
    
    Returns:
        Dict mapping horizon to statistics (mean, median, std)
    """
    stats = {}
    
    for horizon, crps_values in horizons.items():
        if len(crps_values) == 0:
            stats[horizon] = {"mean": 0.0, "median": 0.0, "std": 0.0, "count": 0}
            continue
        
        values_array = np.array(crps_values)
        stats[horizon] = {
            "mean": float(np.mean(values_array)),
            "median": float(np.median(values_array)),
            "std": float(np.std(values_array)),
            "count": len(crps_values),
        }
    
    return stats


def calculate_rolling_averages(
    crps_results: List[Dict[str, Any]],
    window_days: int = 7,
) -> pd.DataFrame:
    """
    Calculate rolling averages of CRPS by asset.
    
    Args:
        crps_results: List of CRPS result dicts
        window_days: Rolling window size in days
    
    Returns:
        DataFrame with rolling averages
    """
    if not crps_results:
        return pd.DataFrame()
    
    # Convert to DataFrame
    df_data = []
    for result in crps_results:
        df_data.append({
            "date": datetime.fromisoformat(result["t0"]).date(),
            "asset": result["asset"],
            "total_crps": result["total_crps"],
            "prompt": result["prompt"],
        })
    
    df = pd.DataFrame(df_data)
    
    if df.empty:
        return df
    
    # Calculate rolling averages per asset
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values(["date", "asset"])
    
    # Group by asset and calculate rolling mean
    df["rolling_crps"] = (
        df.groupby("asset")["total_crps"]
        .rolling(window=f"{window_days}D", on="date", min_periods=1)
        .mean()
        .reset_index(level=0, drop=True)
    )
    
    return df


def generate_diagnostics_report(
    crps_results: List[Dict[str, Any]],
    price_paths_dict: Optional[Dict[str, np.ndarray]] = None,
    realized_prices_dict: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """
    Generate comprehensive diagnostics report.
    
    Returns:
        Dict containing all diagnostic metrics
    """
    report = {}
    
    # Coverage rates (if data available)
    if price_paths_dict and realized_prices_dict:
        coverage_rates = calculate_coverage_rates(
            crps_results, price_paths_dict, realized_prices_dict
        )
        report["coverage_rates"] = coverage_rates
    else:
        report["coverage_rates"] = None
    
    # CRPS by horizon
    horizons = split_crps_by_horizon(crps_results)
    horizon_stats = calculate_horizon_statistics(horizons)
    report["horizon_statistics"] = horizon_stats
    
    # Rolling averages
    rolling_df = calculate_rolling_averages(crps_results, window_days=7)
    report["rolling_averages"] = rolling_df.to_dict("records") if not rolling_df.empty else []
    
    # Overall statistics
    total_crps_values = [r["total_crps"] for r in crps_results if r["total_crps"] > 0]
    if total_crps_values:
        report["overall_statistics"] = {
            "mean_crps": float(np.mean(total_crps_values)),
            "median_crps": float(np.median(total_crps_values)),
            "std_crps": float(np.std(total_crps_values)),
            "min_crps": float(np.min(total_crps_values)),
            "max_crps": float(np.max(total_crps_values)),
            "count": len(total_crps_values),
        }
    else:
        report["overall_statistics"] = None
    
    # By asset
    by_asset = {}
    for result in crps_results:
        asset = result["asset"]
        if asset not in by_asset:
            by_asset[asset] = []
        if result["total_crps"] > 0:
            by_asset[asset].append(result["total_crps"])
    
    report["by_asset"] = {
        asset: {
            "mean": float(np.mean(values)),
            "count": len(values),
        }
        for asset, values in by_asset.items()
        if values
    }
    
    return report


def print_diagnostics_report(report: Dict[str, Any]):
    """Print diagnostics report in readable format."""
    print("\n" + "=" * 60)
    print("DIAGNOSTICS REPORT")
    print("=" * 60)
    
    # Coverage rates
    if report.get("coverage_rates"):
        print("\nCoverage Rates:")
        for quantile, rate in report["coverage_rates"].items():
            print(f"  {quantile}: {rate:.2%}")
    
    # Horizon statistics
    print("\nCRPS by Horizon:")
    for horizon, stats in report.get("horizon_statistics", {}).items():
        print(f"  {horizon}:")
        print(f"    Mean: {stats['mean']:.4f}")
        print(f"    Median: {stats['median']:.4f}")
        print(f"    Std: {stats['std']:.4f}")
        print(f"    Count: {stats['count']}")
    
    # Overall statistics
    if report.get("overall_statistics"):
        overall = report["overall_statistics"]
        print("\nOverall Statistics:")
        print(f"  Mean CRPS: {overall['mean_crps']:.4f}")
        print(f"  Median CRPS: {overall['median_crps']:.4f}")
        print(f"  Std CRPS: {overall['std_crps']:.4f}")
        print(f"  Count: {overall['count']}")
    
    # By asset
    if report.get("by_asset"):
        print("\nBy Asset:")
        for asset, stats in report["by_asset"].items():
            print(f"  {asset}: mean={stats['mean']:.4f}, count={stats['count']}")
    
    print("\n" + "=" * 60)
