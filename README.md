# ⚡ Mac Volt Monitor

A professional, real-time power visualization tool for macOS. Monitor your battery health, power consumption, and charger statistics with a high-performance, `htop`-style terminal interface.

![Demo](https://via.placeholder.com/800x400?text=Mac+Volt+Monitor+Interface)

## ✨ Features

- **🚀 Ultra-Responsive**: High-frequency UI refresh (5Hz) with non-blocking background data collection.
- **🔋 Battery Insights**: Real-time percentage, health (%), cycle count, and detailed condition monitoring.
- **🔌 Charger Intelligence**: Live wattage, voltage, and current monitoring for connected power adapters.
- **📈 Live Graphs**: Real-time ASCII power consumption history.
- **♻️ Power Modes**:
  - **Performance**: 0.5s updates for active debugging.
  - **Balanced**: 2.0s updates for standard monitoring (Default).
  - **Eco**: 5.0s updates for absolute minimum battery impact.
- **🛡️ Secure & Lightweight**: No third-party dependencies. Built with native Python modules and secure system calls.

## 🚀 Getting Started

### Prerequisites
- macOS (tested on Intel and Apple Silicon)
- Python 3.6+

### Usage
Simply run the script directly from your terminal:

```bash
python3 power_monitor.py
```

### Controls
| Key | Action |
| :--- | :--- |
| **P** | Switch to **Performance** Mode (0.5s poll) |
| **B** | Switch to **Balanced** Mode (2.0s poll) |
| **E** | Switch to **Eco** Mode (5.0s poll) |
| **Q** | Quit the application |

## 🛠️ Accuracy Note
The tool uses `ioreg` and `pmset` for the most accurate and real-time data available from the macOS kernel. Some metrics (like Battery Condition) are polled on a longer interval (30s) to maintain maximum efficiency.

## 📜 License
This project is licensed under the **MIT License** - see the [LICENSE](LICENSE) file for details.

---
*Created with ❤️ for Mac Enthusiasts*
