# PyOBS Performance Benchmark Report

**Generated:** 2026-02-08T21:32:22.566596

## Test Environment

| Property | Value |
|----------|-------|
| os | Darwin |
| os_version | 21.6.0 |
| python_version | 3.13.5 |
| cpu | i386 |
| cpu_count | 8 |
| machine | x86_64 |

## Summary

- Total benchmarks: 24
- Categories: obs_write, obs_read, obs_metadata, obs_operations, obs_rest_write, obs_rest_read, obs_rest_metadata, obs_rest_operations

## Obs Write

| Benchmark | Mean | P50 | P99 | ops/sec | MB/s |
|-----------|------|-----|-----|---------|------|
| write_1KB | 197.085ms | 196.833ms | 215.959ms | 5.1 | 0.00 |
| write_64KB | 268.123ms | 270.614ms | 278.105ms | 3.7 | 0.23 |
| write_1MB | 461.372ms | 454.778ms | 522.695ms | 2.2 | 2.17 |

## Obs Read

| Benchmark | Mean | P50 | P99 | ops/sec | MB/s |
|-----------|------|-----|-----|---------|------|
| read_1KB | 191.837ms | 191.342ms | 212.891ms | 5.2 | 0.01 |
| read_64KB | 281.009ms | 278.745ms | 323.792ms | 3.6 | 0.22 |
| read_1MB | 455.643ms | 455.201ms | 504.189ms | 2.2 | 2.19 |

## Obs Metadata

| Benchmark | Mean | P50 | P99 | ops/sec |
|-----------|------|-----|-----|--------|
| stat | 188.406ms | 188.767ms | 198.780ms | 5.3 |
| exists | 194.839ms | 191.261ms | 288.976ms | 5.1 |
| list_100 | 243.429ms | 242.571ms | 254.506ms | 4.1 |

## Obs Operations

| Benchmark | Mean | P50 | P99 | ops/sec |
|-----------|------|-----|-----|--------|
| mkdir | 379.582ms | 383.365ms | 408.988ms | 2.6 |
| delete | 379.201ms | 372.624ms | 421.029ms | 2.6 |
| copy | 231.518ms | 208.051ms | 465.408ms | 4.3 |

## Obs Rest Write

| Benchmark | Mean | P50 | P99 | ops/sec | MB/s |
|-----------|------|-----|-----|---------|------|
| rest_write_1KB | 50.647ms | 46.213ms | 120.676ms | 19.7 | 0.02 |
| rest_write_64KB | 48.076ms | 47.750ms | 57.905ms | 20.8 | 1.30 |
| rest_write_1MB | 96.516ms | 84.072ms | 344.376ms | 10.4 | 10.36 |

## Obs Rest Read

| Benchmark | Mean | P50 | P99 | ops/sec | MB/s |
|-----------|------|-----|-----|---------|------|
| rest_read_1KB | 51.076ms | 45.187ms | 113.627ms | 19.6 | 0.02 |
| rest_read_64KB | 88.095ms | 65.501ms | 515.857ms | 11.4 | 0.71 |
| rest_read_1MB | 80.312ms | 78.828ms | 106.736ms | 12.5 | 12.45 |

## Obs Rest Metadata

| Benchmark | Mean | P50 | P99 | ops/sec |
|-----------|------|-----|-----|--------|
| rest_stat | 46.518ms | 44.236ms | 86.726ms | 21.5 |
| rest_exists | 44.951ms | 44.537ms | 47.857ms | 22.2 |
| rest_list_100 | 58.290ms | 58.317ms | 59.431ms | 17.2 |

## Obs Rest Operations

| Benchmark | Mean | P50 | P99 | ops/sec |
|-----------|------|-----|-----|--------|
| rest_mkdir | 46.924ms | 46.169ms | 54.124ms | 21.3 |
| rest_delete | 97.002ms | 92.728ms | 134.392ms | 10.3 |
| rest_copy | 67.099ms | 61.147ms | 113.214ms | 14.9 |

## PyOBS fsspec vs OBS REST API

| Operation | fsspec Mean | REST Mean | Overhead | fsspec MB/s | REST MB/s |
|-----------|------------|-----------|----------|-------------|----------|
| copy | 231.518ms | 67.099ms | +245.0% | - | - |
| delete | 379.201ms | 97.002ms | +290.9% | - | - |
| exists | 194.839ms | 44.951ms | +333.4% | - | - |
| list_100 | 243.429ms | 58.290ms | +317.6% | - | - |
| mkdir | 379.582ms | 46.924ms | +708.9% | - | - |
| read_1KB | 191.837ms | 51.076ms | +275.6% | 0.01 | 0.02 |
| read_1MB | 455.643ms | 80.312ms | +467.3% | 2.19 | 12.45 |
| read_64KB | 281.009ms | 88.094ms | +219.0% | 0.22 | 0.71 |
| stat | 188.406ms | 46.518ms | +305.0% | - | - |
| write_1KB | 197.085ms | 50.647ms | +289.1% | 0.00 | 0.02 |
| write_1MB | 461.372ms | 96.516ms | +378.0% | 2.17 | 10.36 |
| write_64KB | 268.123ms | 48.076ms | +457.7% | 0.23 | 1.30 |

