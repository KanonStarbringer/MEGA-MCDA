# 🌐 MEGA-MCDA

[![Python](https://img.shields.io/badge/Python-3.8%2B-blue?logo=python)]()
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Repo Size](https://img.shields.io/github/repo-size/KanonStarbringer/MEGA-MCDA.svg)]()
[![Last Commit](https://img.shields.io/github/last-commit/KanonStarbringer/MEGA-MCDA.svg)]()

> **MEGA-MCDA** is a modular and extensible framework for **Multi-Criteria Decision Analysis (MCDA)** methods.  
> It serves as a **unified web environment** to experiment with, compare, and visualize results from classical and emerging MCDA techniques.

---

## 📘 Overview

The **MEGA-MCDA** project was created to provide a single, evolving platform where researchers and decision-makers can easily test and deploy MCDA methods.  
It is ideal for academic experiments, decision dashboards, and strategy evaluation tools.

Supported goals include:
- Integration of **multiple MCDA models** (THOR, TOPSIS, VIKOR, ELECTRE, WENSLO-ARLON, MEREC, SMAA, etc.)
- Easy **local setup** for reproducible experiments
- A **web-based interface** for user interaction and visualization
- A **method-agnostic architecture** to plug in new techniques seamlessly

---

## ✨ Features

- 🧮 Unified MCDA environment with modular method integration  
- 🧰 Flask-based web interface for intuitive exploration  
- 📊 Real-time ranking and scoring visualization  
- 📂 Configurable input structure (alternatives × criteria × weights)  
- 🔄 Continuous integration of new MCDA approaches  
- 🧠 Research-ready foundation for hybrid, fuzzy, or stochastic MCDA models  

---

## 🚀 Quickstart

### 1️⃣ Clone the Repository

```bash
git clone https://github.com/KanonStarbringer/MEGA-MCDA.git
cd MEGA-MCDA
```

### 2️⃣ Install Dependencies

You can either use the setup script or install manually:

```bash
chmod +x setup.sh
./setup.sh
```
or
```bash
pip install -r requirements.txt
```

### 3️⃣ Run the Application

```bash
python app.py
```

Then open your browser and visit:

👉 **http://localhost:5000**

---

## 🧭 Usage

Once the web app starts, you can:

1. **Select** an MCDA method (e.g. TOPSIS, THOR, ELECTRE).  
2. **Upload** or input the decision matrix (alternatives × criteria).  
3. **Set weights** and preference directions (Max/Min).  
4. **Compute** and **visualize rankings** and sensitivity results.  
5. **Export** results for reporting or comparison.

Example (if you plan to expose a Python API later):

```python
from mcda_app import MCDA

model = MCDA(method="TOPSIS", data="data.csv", weights="weights.csv")
ranking = model.run()
print(ranking)
```

---

## 🧩 Project Structure

```
MEGA-MCDA/
├── app.py               # Main Flask app entry point
├── setup.sh             # Environment setup script
├── requirements.txt     # Python dependencies
├── static/              # CSS / JS / assets for UI
├── templates/           # HTML templates (Flask)
├── methods/             # (Planned) MCDA method implementations
├── docs/                # Documentation and screenshots
└── LICENSE              # MIT License
```

---

## 📊 Example Interface

*(You can later add screenshots or GIFs here)*

```markdown
![Home Interface](docs/screenshots/home.png)
![Ranking Visualization](docs/screenshots/results.png)
```

---

## 🔧 Technologies

- **Python** (3.8+)  
- **Flask** — for web app structure  
- **Jinja2 / Bootstrap** — for front-end rendering  
- **NumPy / Pandas** — for matrix computation  
- **Matplotlib / Plotly** — for visualization  

---

## 🧭 Roadmap

| Status | Feature |
|:------:|:--------|
| ✅ | Core Flask web app |
| ✅ | Modular MCDA architecture |
| 🚧 | Integration of THOR, MEREC, WENSLO-ARLON, SMAA |
| 🚧 | Result visualizations (charts, sensitivity analysis) |
| ⬜ | Export to CSV/PDF |
| ⬜ | Docker deployment |
| ⬜ | Multi-user session support |

---

## 🤝 Contributing

Contributions are welcome! To add new methods or improve the UI:

1. **Fork** this repository  
2. **Create** your branch (`git checkout -b feature-name`)  
3. **Commit** your changes (`git commit -m "Add feature X"`)  
4. **Push** the branch (`git push origin feature-name`)  
5. **Open a Pull Request**

Please follow the code style (PEP8) and ensure reproducibility.

---

## 📚 Citation

If you use this software in your research, please cite it as:

```bibtex
@software{kanonstarbringer2025mega_mcda,
  author  = {Pires, Tullio},
  title   = {MEGA-MCDA: A Modular Framework for Multi-Criteria Decision Analysis},
  year    = {2025},
  url     = {https://github.com/KanonStarbringer/MEGA-MCDA}
}
```

---

## 📜 License

This project is licensed under the **MIT License**.  
See the [LICENSE](LICENSE) file for details.

---

## 🙌 Acknowledgements

Special thanks to:
- The **MCDA research community** for continuous methodological development  
- **UFF (Universidade Federal Fluminense)** for academic support  
- Everyone contributing to open-source decision analysis tools  

---

### 💡 Author

**Tullio Pires**  
Researcher in Operations Research & Multi-Criteria Decision Analysis  
[GitHub Profile →](https://github.com/KanonStarbringer)

---

> “Decision-making is the art of balancing criteria in pursuit of clarity.”
