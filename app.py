import streamlit as st
import pandas as pd
import numpy as np
import xlsxwriter
import openpyxl
from st_aggrid import AgGrid
import io
from scipy.integrate import quad
from scipy.stats import kendalltau
from reportlab.lib.pagesizes import letter, A4
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle
import plotly.express as px
import plotly.graph_objects as go
import itertools
from numpy.random import default_rng

# Set the app title and description
st.set_page_config(
    page_title="MEGA-MCDA",
    #page_icon=":chart_with_upwards_trend:",  # You can customize the icon
    #layout="wide",  # You can set the layout (wide or center)
    initial_sidebar_state="auto"  # You can set the initial sidebar state
)

def download_template():
    # Adjust based on the number of alternatives and criteria
    num_alternatives = 9  # You can set a default number or ask the user for input
    num_criteria = 17  # Same for criteria

    # Generate a list of alternative names
    alternatives = [f'A{i+1}' for i in range(num_alternatives)]

    # Create data for the template: "C1", "C2", ..., in the first row, and "Max/Min" in the second row
    criteria_labels = [f'C{i+1}' for i in range(num_criteria)]
    benefit_cost_row = ['Max' if i < 10 else 'Min' for i in range(num_criteria)]  # First 10 are Max, rest are Min

    # Prepare data for the DataFrame
    data = {f'C{i+1}': [''] * num_alternatives for i in range(num_criteria)}
    df = pd.DataFrame(data)

    # Set the first row for the "C1", "C2", ..., and second row for the "Max/Min"
    df.loc[-2] = criteria_labels
    df.loc[-1] = benefit_cost_row
    df.index = df.index + 2  # Shifting the index to make space for the new rows
    df = df.sort_index()

    # Add the "A/C" column for alternatives
    df.insert(0, 'A/C', ['A/C'] + [''] + alternatives)

    # Convert the DataFrame to an Excel file
    excel_buffer = io.BytesIO()
    with pd.ExcelWriter(excel_buffer, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, header=False)

    # Provide a download link for the template
    st.download_button(
        label="Download Excel template",
        data=excel_buffer,
        file_name="MEGA-MCDA_template.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

def prepare_payoff_matrix(df):
    """
    Garante nomes de alternativas na coluna A/C e colunas de critérios numéricas (float).
    Evita TypeError ao normalizar DataFrames lidos como object pelo Excel/AgGrid.
    """
    prepared = df.copy()
    prepared.columns = ['A/C'] + [f'C{i+1}' for i in range(len(prepared.columns) - 1)]
    prepared['A/C'] = prepared['A/C'].astype(str).str.strip()
    prepared = prepared[prepared['A/C'].ne('') & prepared['A/C'].str.lower().ne('nan')]

    for col in prepared.columns[1:]:
        prepared[col] = pd.to_numeric(prepared[col], errors='coerce').astype(float)

    return prepared.reset_index(drop=True)


def as_weight_array(weights):
    """Converte pesos para array 1D posicional (compatível com pandas 3.x)."""
    if isinstance(weights, pd.Series):
        return weights.to_numpy(dtype=float).reshape(-1)
    return np.asarray(weights, dtype=float).reshape(-1)


def criteria_values(df):
    """Retorna matriz numérica alternativas x critérios."""
    return df.iloc[:, 1:].to_numpy(dtype=float)


# Function to read Excel file
def read_excel(uploaded_file):
    df = pd.read_excel(uploaded_file)

    # Show the first two rows for debugging purposes
    #st.write("First Row (Headers):")
    #st.write(df.columns.tolist())
    
    #st.write("Second Row (Criterion Types):")
    #st.write(df.iloc[0, 1:].tolist())

    # Extract the "Max" or "Min" labels from the second row (the row defining if it's Benefit or Cost)
    criterion_types = df.iloc[0, 1:].apply(lambda x: 'Benefit' if str(x).strip().lower() == 'max' else 'Cost').tolist()

    # Remove the second row (the row with "Max" or "Min" labels) from the DataFrame
    df = df.drop(0).reset_index(drop=True)

    # Rename columns to C1, C2, etc. and keep the first column as 'A/C'
    num_criteria = len(df.columns) - 1
    columns = ['A/C'] + [f'C{i+1}' for i in range(num_criteria)]
    df.columns = columns

    df = prepare_payoff_matrix(df)
    return df, criterion_types, df.shape[0], len(df.columns) - 1

def get_payoff_matrix():
    num_alternatives = st.number_input("Enter the number of alternatives:", min_value=2, value=2, step=1)
    num_criteria = st.number_input("Enter the number of criteria:", min_value=1, value=1, step=1)

    # Create a DataFrame to hold the payoff matrix
    columns = ['A/C'] + [f'C{i+1}' for i in range(num_criteria)]
    data = [[f'A{j+1}'] + [0 for _ in range(num_criteria)] for j in range(num_alternatives)]
    payoff_matrix = pd.DataFrame(data, columns=columns)

    # Create an ag-Grid component
    grid_response = AgGrid(payoff_matrix, editable=True, index=False, fit_columns_on_grid_load=True)

    # Get the edited DataFrame from the AgGrid response
    edited_matrix = grid_response['data']

    # Get the type of each criterion (Benefit or Cost)
    criterion_types = []
    for i in range(num_criteria):
        criterion_label = f"C{i+1}"
        criterion_type = st.selectbox(f"{criterion_label} - Benefit or Cost?", ["Benefit", "Cost"])
        criterion_types.append(criterion_type)

    return prepare_payoff_matrix(edited_matrix), criterion_types


def normalize_matrix(df, criterion_types):
    prepared = prepare_payoff_matrix(df)
    normalized_df = prepared.copy()
    for j, criterion_type in enumerate(criterion_types):
        col = normalized_df.columns[j + 1]
        values = normalized_df[col].to_numpy(dtype=float)
        if criterion_type == "Benefit":
            col_max = np.nanmax(values)
            if not np.isfinite(col_max) or col_max == 0:
                col_max = 1e-10
            normalized_df[col] = values / col_max
        else:
            col_min = np.nanmin(values)
            with np.errstate(divide='ignore', invalid='ignore'):
                normalized = col_min / values
            normalized = np.where(np.isfinite(normalized), normalized, 0.0)
            normalized_df[col] = normalized
    return normalized_df

# --- CRITIC-5N-PROVAN helpers ---
def normalize_matrix_max_min(df, criterion_types):
    normalized = df.copy()
    for j, criterion_type in enumerate(criterion_types):
        col_max = df.iloc[:, j+1].max()
        col_min = df.iloc[:, j+1].min()
        if criterion_type == "Benefit":
            normalized.iloc[:, j+1] = (df.iloc[:, j+1] - col_min) / (col_max - col_min)
        else:
            normalized.iloc[:, j+1] = (col_max - df.iloc[:, j+1]) / (col_max - col_min)
    return normalized


def normalize_matrix_linear_sum(df, criterion_types):
    normalized = df.copy()
    for j, criterion_type in enumerate(criterion_types):
        if criterion_type == "Benefit":
            normalized.iloc[:, j+1] = df.iloc[:, j+1] / sum(df.iloc[:, j+1])
        else:
            normalized.iloc[:, j+1] = 1 / df.iloc[:, j+1] / sum(1 / df.iloc[:, j+1])
    return normalized


def normalize_matrix_with_vector(df, criterion_types):
    normalized = df.copy()
    for j, criterion_type in enumerate(criterion_types):
        if criterion_type == "Benefit":
            normalized.iloc[:, j+1] = df.iloc[:, j+1] / np.sqrt(sum(df.iloc[:, j+1] ** 2))
        else:
            normalized.iloc[:, j+1] = 1 - df.iloc[:, j+1] / np.sqrt(sum((1 - df.iloc[:, j+1]) ** 2))
    return normalized


def normalize_matrix_logarithmic(df, criterion_types):
    """
    Normalização logarítmica conforme fórmula N4:
    - Benefit: η_ij(4) = (ln x_ij) / (ln (Π x_ij))
    - Cost: η_ij(4) = (1 / (m-1)) * (1 - (ln x_ij) / (ln (Π x_ij)))
    """
    normalized = df.copy()
    m = int(df.shape[0])
    if m < 2:
        raise ValueError("É necessário pelo menos 2 alternativas para a normalização logarítmica.")
    for j, criterion_type in enumerate(criterion_types):
        col_values = df.iloc[:, j+1].values.astype(float)
        if np.any(col_values <= 0) or np.any(np.isnan(col_values)):
            raise ValueError(
                f"Coluna C{j+1} contém valores zero, negativos ou NaN. "
                "A normalização logarítmica requer valores positivos."
            )
        log_values = np.log(col_values)
        log_product = float(np.sum(log_values))
        if abs(log_product) < 1e-10:
            raise ValueError(
                f"Coluna C{j+1}: log do produtório é muito próximo de zero, causando divisão por zero."
            )
        if criterion_type == "Benefit":
            normalized_values = log_values / log_product
        else:
            normalized_values = (1.0 / float(m - 1)) * (1.0 - log_values / log_product)
        normalized_values = np.abs(normalized_values)
        normalized.iloc[:, j+1] = normalized_values.astype(float)
    return normalized


def normalize_matrix_non_linear(df, criterion_types):
    normalized = df.copy()
    for j, criterion_type in enumerate(criterion_types):
        if criterion_type == "Benefit":
            normalized.iloc[:, j+1] = (df.iloc[:, j+1] / max(df.iloc[:, j+1])) ** 2
        else:
            normalized.iloc[:, j+1] = (min(df.iloc[:, j+1]) / df.iloc[:, j+1]) ** 3
    return normalized


def aczel_alsina_provan_matrix(normalized_matrices, phis=None, xi=1.0, eps=1e-12):
    if not normalized_matrices:
        raise ValueError("normalized_matrices must be a non-empty list of DataFrames")
    K = len(normalized_matrices)
    base_df = normalized_matrices[0]
    for mat in normalized_matrices[1:]:
        if not mat.columns.equals(base_df.columns) or mat.shape != base_df.shape:
            raise ValueError("All normalized matrices must have the same shape and columns")
    crit_cols = base_df.columns[1:]
    X = np.stack(
        [mat[crit_cols].to_numpy(dtype=float) for mat in normalized_matrices],
        axis=0
    )
    if phis is None:
        phis_arr = np.ones(K, dtype=float) / K
    else:
        phis_arr = np.asarray(phis, dtype=float)
        if phis_arr.shape != (K,):
            raise ValueError("phis must have length K (same as normalized_matrices)")
        s = phis_arr.sum()
        if s <= 0:
            raise ValueError("Sum of φ_k must be positive")
        phis_arr = phis_arr / s
    if xi <= 0:
        raise ValueError("xi must be > 0")
    S = X.sum(axis=0)
    S_safe = np.where(S > eps, S, 1.0)
    F = X / S_safe
    F = np.clip(F, eps, 1.0 - eps)
    inner = np.sum(
        phis_arr[:, None, None] * (-np.log(1.0 - F)) ** xi,
        axis=0
    )
    A = 1.0 - np.exp(-inner ** (1.0 / xi))
    eta = np.where(S > eps, S * A, 0.0)
    result = base_df.copy()
    result.loc[:, crit_cols] = eta
    return result


def critic_weights_provan(df):
    std_dev = df.iloc[:, 1:].std(axis=0)
    corr_matrix = df.iloc[:, 1:].corr(method="pearson")
    info_measure = np.zeros(len(std_dev))
    for j in range(len(std_dev)):
        sum_corr = np.sum(1 - corr_matrix.iloc[j, :])
        info_measure[j] = std_dev.iloc[j] * sum_corr
    weights = info_measure / np.sum(info_measure)
    return weights


def apply_critic_weights_provan(df_agg):
    weights = critic_weights_provan(df_agg)
    crit_cols = df_agg.columns[1:]
    weighted_df = df_agg.copy()
    weighted_df.loc[:, crit_cols] = df_agg.loc[:, crit_cols] * weights
    return weights, weighted_df


def provan_ranking(df_agg, criterion_types):
    weights, weighted_df = apply_critic_weights_provan(df_agg)
    crit_cols = weighted_df.columns[1:]
    theta = weighted_df.loc[:, crit_cols].to_numpy(dtype=float)
    benefit_idx = [j for j, t in enumerate(criterion_types) if t == "Benefit"]
    cost_idx = [j for j, t in enumerate(criterion_types) if t == "Cost"]
    if benefit_idx:
        U_plus = theta[:, benefit_idx].sum(axis=1)
    else:
        U_plus = np.zeros(theta.shape[0])
    if cost_idx:
        U_minus = theta[:, cost_idx].sum(axis=1)
    else:
        U_minus = np.zeros(theta.shape[0])
    Score = (2.0 + U_plus) / (2.0 + U_minus)
    result = pd.DataFrame({
        "A/C": weighted_df["A/C"],
        "U_plus": U_plus,
        "U_minus": U_minus,
        "Score": Score
    })
    result["Rank"] = result["Score"].rank(ascending=False, method="dense").astype(int)
    result = result.sort_values(by="Score", ascending=False).reset_index(drop=True)
    return result, weights, weighted_df

def calculate_v_ij(normalized_df):
    v_values = normalized_df.iloc[:, 1:].mean()
    return v_values

def calculate_p_ij(normalized_df, v_values):
    p_values = ((normalized_df.iloc[:, 1:] - v_values) ** 2).sum()
    return p_values

def calculate_phi_j(p_values):
    phi_values = 1 - p_values
    return phi_values

def calculate_psi_j(phi_values):
    psi_values = phi_values / phi_values.sum()
    return psi_values

def calculate_w_ij(p_values):
    w_values = p_values / p_values.sum()
    return w_values

def calculate_variables(normalized_df):
    v_values = calculate_v_ij(normalized_df)
    p_values = calculate_p_ij(normalized_df, v_values)
    w_values = calculate_w_ij(p_values)
    variables_df = pd.DataFrame({'v': v_values, 'p': p_values, 'w': w_values})
    return variables_df

def calculate_PSI_variables(normalized_df):
    v_values = calculate_v_ij(normalized_df)
    p_values = calculate_p_ij(normalized_df, v_values)
    phi_values = calculate_phi_j(p_values)
    psi_values = calculate_psi_j(phi_values)
    PSI_variables_df = pd.DataFrame({'phi': phi_values, 'psi': psi_values})
    return PSI_variables_df

def calculate_new_matrix(normalized_df, w_values):
    new_matrix = normalized_df.copy()
    new_matrix.iloc[:, 1:] = new_matrix.iloc[:, 1:] * w_values.values
    return new_matrix

def create_set_Sj(normalized_df):
    set_Sj = {}
    for col in normalized_df.columns[1:]:
        set_Sj[col] = normalized_df[col].max()
    return set_Sj

def split_sets_Smax_Smin(criterion_types, set_Sj):
    set_Smax = {}
    set_Smin = {}
    for col, val in set_Sj.items():
        if criterion_types[int(col[1:]) - 1] == "Benefit":
            set_Smax[col] = val
        else:
            set_Smin[col] = val
    return set_Smax, set_Smin

def create_set_Tmax_Tmin(new_matrix, criterion_types):
    set_Tmax = {}
    set_Tmin = {}
    for i, alternative in enumerate(new_matrix['A/C']):
        T_max = []
        T_min = []
        for j, criterion_type in enumerate(criterion_types):
            col = f"C{j+1}"
            if criterion_type == "Benefit":
                T_max.append(new_matrix[col].iloc[i])
            else:
                T_min.append(new_matrix[col].iloc[i])
        set_Tmax[alternative] = T_max
        set_Tmin[alternative] = T_min
    return set_Tmax, set_Tmin

def calculate_T_ik_T_il(set_Tmax, set_Tmin):
    T_ik = {}
    T_il = {}
    for alternative, Tmax in set_Tmax.items():
        T_ik[alternative] = sum(Tmax)
    for alternative, Tmin in set_Tmin.items():
        T_il[alternative] = sum(Tmin)
    return T_ik, T_il

def optimal_alternative_function(Sk, Sl):
    def f_opt(x):
        return (Sl - Sk) * x + Sk
    return f_opt

def alternative_function(T_ik, T_il):
    def f_i(x):
        return (T_il - T_ik) * x + T_ik
    return f_i

def calculate_definite_integral(func, a, b):
    integral_value, _ = quad(func, a, b)
    return integral_value


def generate_pdf_report(payoff_matrix, normalized_matrix, variables_df, new_matrix,
                        set_Sj, set_Smax, set_Smin, set_Tmax, set_Tmin, T_ik, T_il,
                        def_opt_integral, alternative_functions, def_integrals, ranked_alternatives,
                        Sk, Sl):

    # Create a PDF document in memory using BytesIO
    buffer = io.BytesIO()
    
    # Create a new PDF document using SimpleDocTemplate with A4 paper size
    doc = SimpleDocTemplate("mcda_report.pdf", pagesize=A4)

    # Define styles for the report
    styles = getSampleStyleSheet()

    # Add the content to the PDF using a list of flowables
    elements = []

    # Add the title and other content to elements list using Paragraph
    title_text = "MPSI-MARA Hybrid Method MCDA Report"
    elements.append(Paragraph(title_text, styles['Title']))

    # Add the payoff matrix as a table to the PDF
    payoff_table_data = [['A/C'] + list(payoff_matrix.columns[1:])] + payoff_matrix.values.tolist()
    payoff_table = Table(payoff_table_data)
    # Apply TableStyle to the table for better formatting (optional)
    style = TableStyle([('BACKGROUND', (0, 0), (-1, 0), colors.grey),
                        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
                        ('GRID', (0, 0), (-1, -1), 1, colors.black)])
    payoff_table.setStyle(style)
    elements.append(payoff_table)

    # Add the optimal alternative function, alternative functions, definite integrals, and ranking
    # to the PDF using Paragraph

    elements.append(Paragraph("Optimal Alternative Function:", styles['Heading2']))
    elements.append(Paragraph(f"f_opt(x) = ({Sl} - {Sk}) * x + {Sk}", styles['Normal']))

    elements.append(Paragraph("Alternative Functions:", styles['Heading2']))
    for alternative, f_i in alternative_functions.items():
        elements.append(Paragraph(f"f_{alternative}(x) = ({T_il[alternative]} - {T_ik[alternative]}) * x + {T_ik[alternative]}", styles['Normal']))

    elements.append(Paragraph("Definite Integrals of Alternative Functions:", styles['Heading2']))
    for alternative, def_i_integral in def_integrals.items():
        elements.append(Paragraph(f"Definite Integral of f_{alternative}(x): {def_i_integral}", styles['Normal']))

    elements.append(Paragraph(f"Definite Integral of Optimal Alternative Function: {def_opt_integral}", styles['Heading2']))

    elements.append(Paragraph("Ranking of Alternatives:", styles['Heading2']))
    for rank, (alternative, difference) in enumerate(ranked_alternatives, start=1):
        elements.append(Paragraph(f"Rank {rank}: Alternative {alternative}, Difference: {difference:.4f}", styles['Normal']))

    # Save the generated PDF in a BytesIO object
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    doc.build(elements)

    # Reset the buffer position to the beginning
    buffer.seek(0)

    # # Offer the PDF file for download with a download button
    # st.download_button("Download PDF Report", data=buffer, file_name="mcda_report.pdf", mime="application/pdf")

    return buffer

# Function to perform ARLON normalization (Logarithmic)
def arlon_normalize(matrix, criterion_types):
    """
    Performs logarithmic normalization on the decision matrix.
    
    Parameters:
    - matrix: The payoff matrix (alternatives x criteria)
    - criterion_types: A list of "Benefit" or "Cost" for each criterion
    
    Returns:
    - A normalized matrix.
    """
    normalized_matrix = matrix.copy()
    
    for j, criterion_type in enumerate(criterion_types):
        if criterion_type == "Benefit":
            col_min = matrix.iloc[:, j+1].min()  # Skip the 'A/C' column
            col_max = matrix.iloc[:, j+1].max()
            normalized_matrix.iloc[:, j+1] = np.log1p(matrix.iloc[:, j+1] - col_min + 1) / np.log1p(col_max - col_min + 1)
        else:  # Cost criterion
            col_min = matrix.iloc[:, j+1].min()
            col_max = matrix.iloc[:, j+1].max()
            normalized_matrix.iloc[:, j+1] = np.log1p(col_max - matrix.iloc[:, j+1] + 1) / np.log1p(col_max - col_min + 1)
    
    return normalized_matrix


# Function to calculate ARLON weights
def calculate_arlon_weights(normalized_matrix):
    """
    Calculate weights for each criterion based on the normalized matrix.
    
    Parameters:
    - normalized_matrix: The normalized decision matrix.
    
    Returns:
    - A list of weights for each criterion.
    """
    # Sum across all alternatives for each criterion
    column_sums = normalized_matrix.iloc[:, 1:].sum(axis=0)
    
    # Calculate weights as the proportion of each column's sum to the total sum
    total_sum = column_sums.sum()
    weights = column_sums / total_sum
    
    return weights

# Function to calculate final rankings using ARLON
def calculate_arlon_rankings(normalized_matrix, weights):
    """
    Calculate the final rankings for the alternatives based on ARLON weights.
    
    Parameters:
    - normalized_matrix: The normalized decision matrix.
    - weights: Weights for each criterion.
    
    Returns:
    - A DataFrame containing the ranking of each alternative.
    """
    # Apply weights to the normalized matrix (excluding the 'A/C' column)
    weighted_matrix = normalized_matrix.iloc[:, 1:].multiply(weights.values, axis=1)
    
    # Sum across the weighted criteria for each alternative to get final scores
    scores = weighted_matrix.sum(axis=1)
    
    # Create a DataFrame with alternatives and their scores
    rankings = pd.DataFrame({
        'Alternative': normalized_matrix['A/C'],
        'Score': scores
    })
    
    # Sort by score in descending order (higher score is better)
    rankings = rankings.sort_values(by='Score', ascending=False).reset_index(drop=True)
    
    return rankings

def lopcow_normalize(matrix, criterion_types):
    normalized_matrix = matrix.copy()

    # Normalize based on Benefit or Cost criteria
    for j, criterion_type in enumerate(criterion_types):
        if criterion_type == "Benefit":
            col_min = matrix.iloc[:, j+1].min()
            col_max = matrix.iloc[:, j+1].max()
            normalized_matrix.iloc[:, j+1] = (matrix.iloc[:, j+1] - col_min) / (col_max - col_min)
        else:  # Cost criterion
            col_min = matrix.iloc[:, j+1].min()
            col_max = matrix.iloc[:, j+1].max()
            normalized_matrix.iloc[:, j+1] = (col_max - matrix.iloc[:, j+1]) / (col_max - col_min)

    return normalized_matrix

def calculate_lopcow_percentage_values(normalized_matrix):
    """
    Calculate the percentage values (PV) for each criterion according to the LOPCOW method.

    Parameters:
    - normalized_matrix: The matrix with normalized values for each criterion.

    Returns:
    - A list of percentage values for each criterion.
    """
    num_alternatives = normalized_matrix.shape[0]  # m, number of alternatives
    percentage_values = []
    
    for j in range(1, normalized_matrix.shape[1]):  # Skip 'A/C' column
        r_ij_squared_mean = np.mean(np.square(normalized_matrix.iloc[:, j]))
        std_dev = np.std(normalized_matrix.iloc[:, j])  # σ

        # Apply the percentage value formula
        PV_j = np.log(np.abs(np.sqrt(r_ij_squared_mean) / std_dev)) * 100
        percentage_values.append(PV_j)
    
    return percentage_values

def calculate_lopcow_weights(normalized_matrix):
    """
    Calculate weights using the LOPCOW method.
    
    Parameters:
    - normalized_matrix: The normalized matrix after LOPCOW normalization.

    Returns:
    - A list of weights for each criterion.
    """
    num_criteria = normalized_matrix.shape[1] - 1  # Exclude the first column ('A/C')
    percentage_values = calculate_lopcow_percentage_values(normalized_matrix)  # Use previously defined function
    
    # Normalize the percentage values to calculate the weights
    total_PV = np.sum(percentage_values)
    if total_PV == 0:
        total_PV = 1e-10  # Avoid zero division by assigning a small number

    weights = [PV_j / total_PV for PV_j in percentage_values]
    
    return weights

def dobi_normalize(matrix, criterion_types):
    """
    Normalize the payoff matrix for DOBI method based on the distinction between benefit and cost criteria.
    
    Parameters:
    - matrix: The original payoff matrix (alternatives x criteria).
    - criterion_types: A list indicating whether each criterion is 'Benefit' or 'Cost'.
    
    Returns:
    - A normalized matrix.
    """
    normalized_matrix = matrix.copy()
    
    # Loop through each criterion (C1, C2, ..., Cn)
    for j in range(1, matrix.shape[1]):  # Skip the first 'A/C' column
        col_max = matrix.iloc[:, j].max()  # Max value for the criterion (Cj)
        col_min = matrix.iloc[:, j].min()  # Min value for the criterion (Cj)
        
        # Normalize based on the type of the criterion (Benefit or Cost)
        if criterion_types[j-1] == 'Benefit':
            normalized_matrix.iloc[:, j] = matrix.iloc[:, j] / col_max
        else:  # Cost
            normalized_matrix.iloc[:, j] = -(matrix.iloc[:, j] / col_max) + (max(matrix.iloc[:, j] / col_max)) + (min(matrix.iloc[:, j] / col_max))
    
    return normalized_matrix

def dobi_weighted_significance(normalized_matrix, psi1, psi2, zeta, weights):
    """
    Calculate the Z_L_1^(1) and Z_L_1^(2) functions for each alternative.
    
    Parameters:
    - normalized_matrix: The normalized decision matrix (alternatives x criteria)
    - psi1, psi2, zeta: Parameters for the Dombi-Bonferroni functions
    - weights: Weight vector from LOPCOW

    Returns:
    - Z1, Z2 significance values.
    """
    Z_L1 = dobi_Z_L_1(normalized_matrix, weights, psi1, psi2, zeta)
    Z_L2 = dobi_Z_L_2(normalized_matrix, weights, psi1, psi2, zeta)
    
    return Z_L1, Z_L2

def dobi_integrated_value(Z_L1_values, Z_L2_values, delta):
    """
    Calculate the integrated value R_i for each alternative using the DOBI method.
    """
    integrated_values = []
    for Z_L1, Z_L2 in zip(Z_L1_values, Z_L2_values):
        R_i = (Z_L1 + Z_L2) / (1 + ((Z_L1 + Z_L2) / (Z_L1 + Z_L2 + delta)) ** delta)
        integrated_values.append(R_i)
    return integrated_values

def dobi_rank_alternatives(integrated_values, alternatives=None):
    """
    Rank alternatives based on their integrated values using the DOBI method.
    
    Parameters:
    - integrated_values: A list of integrated values for each alternative
    
    Returns:
    - A DataFrame with alternatives and their rankings.
    """
    if alternatives is None:
        alternatives = ['A' + str(i+1) for i in range(len(integrated_values))]

    rankings_df = pd.DataFrame({
        'Alternative': list(alternatives),
        'Integrated Value': integrated_values
    })
    
    # Sort alternatives by integrated value in descending order
    rankings_df = rankings_df.sort_values(by='Integrated Value', ascending=False).reset_index(drop=True)
    
    return rankings_df

# Function f(dhat) as given in the article, normalized
def f_dhat(d_hat_matrix):
    """
    Calculate the f(d_hat) values for the given normalized matrix (d_hat).
    
    Parameters:
    - d_hat_matrix: The normalized matrix (d_hat values).
    
    Returns:
    - A matrix (DataFrame) of f(d_hat) values where each element is divided by the sum of the row.
    """
    # Convert to numeric values, replacing any non-numeric values with 0
    numeric_matrix = d_hat_matrix.iloc[:, 1:].apply(pd.to_numeric, errors='coerce').fillna(0)
    num_alternatives = numeric_matrix.shape[0]
    num_criteria = numeric_matrix.shape[1]

    # Keep the same shape as the criteria matrix (alternatives x criteria).
    f_dhat_matrix = pd.DataFrame(
        0.0,
        index=numeric_matrix.index,
        columns=numeric_matrix.columns
    )

    # Normalize each row by its own sum.
    for i in range(num_alternatives):
        row_sum = numeric_matrix.iloc[i].sum()
        if row_sum == 0:
            row_sum = 1e-10  # Avoid division by zero

        for j in range(num_criteria):
            f_dhat_matrix.iloc[i, j] = numeric_matrix.iloc[i, j] / row_sum

    return f_dhat_matrix


def _dobi_alternative_weights(normalized_matrix_dobi, criteria_weights):
    """
    Build a stable per-alternative weight from criterion weights.
    """
    criteria_values = normalized_matrix_dobi.iloc[:, 1:].apply(pd.to_numeric, errors='coerce').fillna(0.0)
    num_criteria = criteria_values.shape[1]

    weights = np.asarray(criteria_weights, dtype=float)
    if len(weights) < num_criteria:
        missing = num_criteria - len(weights)
        weights = np.concatenate([weights, np.full(missing, 1.0 / num_criteria)])
    elif len(weights) > num_criteria:
        weights = weights[:num_criteria]

    weight_sum = weights.sum()
    if weight_sum == 0:
        weights = np.full(num_criteria, 1.0 / num_criteria)
    else:
        weights = weights / weight_sum

    alt_weights = criteria_values.to_numpy().dot(weights)
    alt_weights = np.where(alt_weights <= 0, 1e-10, alt_weights)
    return alt_weights, weights

# Calculate Z_i^(1) for DOBI method

def Z_i_1_v2(normalized_matrix_dobi, f_dhat_matrix, weights, psi1, psi2, zeta):
    """
    Calculate \mathbb{Z}_{i}^{(1)\psi_1,\psi_2,\zeta} for DOBI method based on the normalized DOBI matrix and f(dhat) matrix.
    """
    num_alternatives = normalized_matrix_dobi.shape[0]
    num_criteria = normalized_matrix_dobi.shape[1] - 1  # Exclude 'A/C' column

    alt_weights, criterion_weights = _dobi_alternative_weights(normalized_matrix_dobi, weights)
    Z_L1_values = []

    # Loop through each alternative
    for i in range(num_alternatives):
        # Step 1: Numerator: Sum of the row (sum of the normalized values for alternative i)
        dhat_i = normalized_matrix_dobi.iloc[i, 1:].apply(pd.to_numeric, errors='coerce').fillna(0)
        sum_dhat = np.sum(dhat_i)

        # Step 2: Calculate the complex denominator
        inner_sum = 0
        for j in range(num_criteria):
            f_dhat_ij = float(f_dhat_matrix.iloc[i, j])  # Ensure numeric value

            # Keep f_dhat in (0, 1) to avoid unstable terms.
            if f_dhat_ij <= 0 or f_dhat_ij >= 1:
                continue

            term1 = 1 / (alt_weights[i] * criterion_weights[j] * (psi1 + psi2))
            term2 = (psi1 * ((1 - f_dhat_ij) / f_dhat_ij)) ** zeta
            term3 = psi2 * (f_dhat_ij / (1 - f_dhat_ij)) ** zeta

            # Add up these terms for the inner sum
            inner_sum += term1 * (term2 + term3)

        # Step 3: Final denominator calculation
        denom = 1 + (1 / (alt_weights[i] * (psi1 + psi2))) * inner_sum
        denom = denom ** (1 / zeta)

        # Step 4: Z_L1 Calculation
        Z_L1 = sum_dhat / denom
        Z_L1_values.append(Z_L1)

    return Z_L1_values

def Z_i_2_v2(normalized_matrix_dobi, f_dhat_matrix, weights, psi1, psi2, zeta):
    """
    Updated version of Z_i_2 function for the DOBI method using normalized DOBI matrix and f(dhat) matrix.
    """
    num_alternatives = normalized_matrix_dobi.shape[0]
    num_criteria = normalized_matrix_dobi.shape[1] - 1  # Exclude 'A/C' column
    alt_weights, criterion_weights = _dobi_alternative_weights(normalized_matrix_dobi, weights)
    Z_L2_values = []
    z_l1_values = Z_i_1_v2(normalized_matrix_dobi, f_dhat_matrix, weights, psi1, psi2, zeta)

    for i in range(num_alternatives):
        # Numerator: Sum of the row (sum of the normalized values for alternative i)
        row_sum = np.sum(normalized_matrix_dobi.iloc[i, 1:].apply(pd.to_numeric, errors='coerce').fillna(0))

        # Subtract the value of Z_L1 from the row sum for the current alternative
        Z_L1_value = z_l1_values[i]
        adjusted_sum = row_sum - Z_L1_value

        # Initialize the denominator
        inner_sum = 0
        for j in range(num_criteria):
            f_dhat_ij = float(f_dhat_matrix.iloc[i, j])  # Ensure numeric value

            # Keep f_dhat in (0, 1) to avoid unstable terms.
            if f_dhat_ij <= 0 or f_dhat_ij >= 1:
                continue

            term1 = 1 / (alt_weights[i] * criterion_weights[j] * (psi1 + psi2))
            term2 = (psi1 * (1 - f_dhat_ij) / f_dhat_ij) ** zeta
            term3 = psi2 * (f_dhat_ij / (1 - f_dhat_ij)) ** zeta
            inner_sum += term1 * (term2 + term3)

        # Calculate final denominator for Z_L2
        denominator = 1 + (1 / (alt_weights[i] * (psi1 + psi2))) * inner_sum
        denominator = denominator ** (1 / zeta)

        Z_L2 = adjusted_sum / denominator
        Z_L2_values.append(Z_L2)

    return Z_L2_values

def dobi_R_i(Z_L1_values, Z_L2_values, delta):
    """
    Calculate the integrated value of DOBI functions R_i based on Eq. (16).
    
    Parameters:
    - Z_L1_values: List of Z_L1 values for each alternative.
    - Z_L2_values: List of Z_L2 values for each alternative.
    - delta: Parameter for the integrated value calculation (δ >= 0).
    
    Returns:
    - A list of integrated R_i values for each alternative.
    """
    R_i_values = []
    
    for i in range(len(Z_L1_values)):
        Z_L1 = Z_L1_values[i]
        Z_L2 = Z_L2_values[i]
        
        # Calculate the numerator: Z_L1 + Z_L2
        numerator = Z_L1 + Z_L2
        
        # Calculate the denominator:
        denom_part1 = (1 - Z_L1) / Z_L1  # (1 - Z_L1) / Z_L1
        denom_part2 = (1 - Z_L2) / Z_L2  # (1 - Z_L2) / Z_L2
        
        denominator = 1 + (0.5 * (denom_part1 ** delta) + 0.5 * (denom_part2 ** delta)) ** delta
        
        # Final R_i calculation
        R_i = numerator / denominator
        R_i_values.append(R_i)
    
    return R_i_values

def swara_normalize(matrix, criterion_types):
    """
    Normalize the decision matrix using SWARA method.
    
    Parameters:
    - matrix: The decision matrix (alternatives x criteria)
    - criterion_types: List of "Benefit" or "Cost" for each criterion
    
    Returns:
    - Normalized matrix
    """
    normalized_matrix = matrix.copy()
    
    for j, criterion_type in enumerate(criterion_types):
        if criterion_type == "Benefit":
            col_max = matrix.iloc[:, j+1].max()
            normalized_matrix.iloc[:, j+1] = matrix.iloc[:, j+1] / col_max
        else:  # Cost criterion
            col_min = matrix.iloc[:, j+1].min()
            normalized_matrix.iloc[:, j+1] = col_min / matrix.iloc[:, j+1]
    
    return normalized_matrix

def calculate_swara_weights(normalized_matrix):
    """
    Calculate weights using SWARA method.
    
    Parameters:
    - normalized_matrix: The normalized decision matrix
    
    Returns:
    - Weights for each criterion
    """
    # Calculate the mean value for each criterion
    mean_values = normalized_matrix.iloc[:, 1:].mean()
    
    # Calculate weights as the proportion of each mean to the total
    total_mean = mean_values.sum()
    return as_weight_array(mean_values / total_mean)

def moora_normalize(matrix):
    """
    Normalize the decision matrix using MOORA method.
    
    Parameters:
    - matrix: The decision matrix
    
    Returns:
    - Normalized matrix
    """
    normalized_matrix = matrix.copy()
    
    # Calculate the square root of the sum of squares for each criterion
    for j in range(1, matrix.shape[1]):
        sum_squares = np.sqrt(np.sum(matrix.iloc[:, j]**2))
        normalized_matrix.iloc[:, j] = matrix.iloc[:, j] / sum_squares
    
    return normalized_matrix

def calculate_moora_scores(normalized_matrix, weights, criterion_types):
    """
    Calculate MOORA scores for each alternative.
    
    Parameters:
    - normalized_matrix: The normalized decision matrix
    - weights: Weights for each criterion
    - criterion_types: List of "Benefit" or "Cost" for each criterion
    
    Returns:
    - MOORA scores for each alternative
    """
    weights = as_weight_array(weights)
    values = criteria_values(normalized_matrix)
    scores = np.zeros(normalized_matrix.shape[0])
    
    for i in range(normalized_matrix.shape[0]):
        for j, criterion_type in enumerate(criterion_types):
            if criterion_type == "Benefit":
                scores[i] += weights[j] * values[i, j]
            else:  # Cost criterion
                scores[i] -= weights[j] * values[i, j]
    
    return scores

def calculate_3nag_scores(moora_scores, normalized_matrix, weights, criterion_types):
    """
    Calculate 3NAG scores for each alternative.
    
    Parameters:
    - moora_scores: MOORA scores for each alternative
    - normalized_matrix: The normalized decision matrix
    - weights: Weights for each criterion
    - criterion_types: List of "Benefit" or "Cost" for each criterion
    
    Returns:
    - 3NAG scores for each alternative
    """
    weights = as_weight_array(weights)
    values = criteria_values(normalized_matrix)
    scores = np.zeros(normalized_matrix.shape[0])
    
    for i in range(normalized_matrix.shape[0]):
        for j, criterion_type in enumerate(criterion_types):
            if criterion_type == "Benefit":
                scores[i] += weights[j] * (values[i, j] - moora_scores[i])
            else:  # Cost criterion
                scores[i] += weights[j] * (moora_scores[i] - values[i, j])
    
    return scores

def rank_alternatives(scores, alternatives=None):
    """
    Rank alternatives based on their scores.
    
    Parameters:
    - scores: Scores for each alternative
    
    Returns:
    - DataFrame with alternatives and their rankings
    """
    scores = np.asarray(scores).reshape(-1)
    if alternatives is None:
        alternatives = [f'A{i+1}' for i in range(len(scores))]
    else:
        alternatives = list(alternatives)
        if len(alternatives) != len(scores):
            # Keep both arrays aligned even if the input table has blank/extra labels.
            min_len = min(len(alternatives), len(scores))
            alternatives = alternatives[:min_len]
            scores = scores[:min_len]

    rankings = pd.DataFrame({
        'Alternative': alternatives,
        'Score': scores
    })
    
    # Sort by score in descending order
    rankings = rankings.sort_values(by='Score', ascending=False).reset_index(drop=True)
    
    return rankings

def critic_normalize(matrix, criterion_types):
    """
    Normalize the decision matrix using CRITIC method.
    
    Parameters:
    - matrix: The decision matrix (alternatives x criteria)
    - criterion_types: List of "Benefit" or "Cost" for each criterion
    
    Returns:
    - Normalized matrix
    """
    normalized_matrix = matrix.copy()
    
    for j, criterion_type in enumerate(criterion_types):
        if criterion_type == "Benefit":
            col_min = matrix.iloc[:, j+1].min()
            col_max = matrix.iloc[:, j+1].max()
            normalized_matrix.iloc[:, j+1] = (matrix.iloc[:, j+1] - col_min) / (col_max - col_min)
        else:  # Cost criterion
            col_min = matrix.iloc[:, j+1].min()
            col_max = matrix.iloc[:, j+1].max()
            normalized_matrix.iloc[:, j+1] = (col_max - matrix.iloc[:, j+1]) / (col_max - col_min)
    
    return normalized_matrix

def calculate_critic_weights(normalized_matrix):
    """
    Calculate weights using CRITIC method.
    
    Parameters:
    - normalized_matrix: The normalized decision matrix
    
    Returns:
    - Weights for each criterion
    """
    # Calculate standard deviation for each criterion
    std_dev = as_weight_array(normalized_matrix.iloc[:, 1:].std())
    
    # Calculate correlation matrix
    correlation_matrix = normalized_matrix.iloc[:, 1:].corr()
    
    # Calculate information measure for each criterion
    info_measure = np.zeros(len(std_dev))
    for j in range(len(std_dev)):
        sum_correlation = np.sum(1 - correlation_matrix.iloc[j, :])
        info_measure[j] = std_dev[j] * sum_correlation
    
    # Calculate weights
    weights = info_measure / np.sum(info_measure)
    
    return weights

def calculate_critic_moora_scores(normalized_matrix, weights, criterion_types):
    """Calculate MOORA scores for each alternative using CRITIC weights."""
    return calculate_moora_scores(normalized_matrix, weights, criterion_types)

def calculate_3n_scores(moora_scores, normalized_matrix, weights, criterion_types):
    """
    Calculate 3N scores for each alternative.
    
    Parameters:
    - moora_scores: MOORA scores for each alternative
    - normalized_matrix: The normalized decision matrix
    - weights: Weights for each criterion
    - criterion_types: List of "Benefit" or "Cost" for each criterion
    
    Returns:
    - 3N scores for each alternative
    """
    weights = as_weight_array(weights)
    values = criteria_values(normalized_matrix)
    scores = np.zeros(normalized_matrix.shape[0])
    
    for i in range(normalized_matrix.shape[0]):
        for j, criterion_type in enumerate(criterion_types):
            if criterion_type == "Benefit":
                scores[i] += weights[j] * (values[i, j] - moora_scores[i])
            else:  # Cost criterion
                scores[i] += weights[j] * (moora_scores[i] - values[i, j])
    
    return scores

def calculate_critic_gra_3n_weights(normalized_matrix):
    """
    Calculate weights using CRITIC-GRA-3N method.
    
    Parameters:
    - normalized_matrix: The normalized decision matrix
    
    Returns:
    - Weights for each criterion
    """
    # Calculate standard deviation for each criterion
    std_dev = as_weight_array(normalized_matrix.iloc[:, 1:].std())
    
    # Calculate correlation matrix
    correlation_matrix = normalized_matrix.iloc[:, 1:].corr()
    
    # Calculate information measure for each criterion
    info_measure = np.zeros(len(std_dev))
    for j in range(len(std_dev)):
        sum_correlation = np.sum(1 - correlation_matrix.iloc[j, :])
        info_measure[j] = std_dev[j] * sum_correlation
    
    # Calculate weights
    weights = info_measure / np.sum(info_measure)
    
    return weights

def calculate_grey_coefficient(normalized_matrix, weights, criterion_types):
    """
    Calculate grey coefficients for each alternative using GRA method.
    
    Parameters:
    - normalized_matrix: The normalized decision matrix
    - weights: Weights for each criterion
    - criterion_types: List of "Benefit" or "Cost" for each criterion
    
    Returns:
    - Grey coefficients for each alternative
    """
    weights = as_weight_array(weights)
    values = criteria_values(normalized_matrix)
    num_criteria = values.shape[1]

    # Define reference sequence (ideal solution)
    reference_sequence = np.zeros(num_criteria)
    for j, criterion_type in enumerate(criterion_types):
        if criterion_type == "Benefit":
            reference_sequence[j] = values[:, j].max()
        else:  # Cost criterion
            reference_sequence[j] = values[:, j].min()
    
    # Calculate grey coefficients
    grey_coefficients = np.zeros(normalized_matrix.shape[0])
    rho = 0.5  # Distinguishing coefficient
    
    for i in range(normalized_matrix.shape[0]):
        sum_coefficient = 0
        for j in range(len(criterion_types)):
            diff = abs(values[i, j] - reference_sequence[j])
            col_diff = np.abs(values[:, j] - reference_sequence[j])
            min_diff = col_diff.min()
            max_diff = col_diff.max()
            grey_coefficient = (min_diff + rho * max_diff) / (diff + rho * max_diff)
            sum_coefficient += weights[j] * grey_coefficient
        grey_coefficients[i] = sum_coefficient
    
    return grey_coefficients

def calculate_3n_grey_scores(grey_coefficients, normalized_matrix, weights, criterion_types):
    """
    Calculate 3N scores for each alternative using grey coefficients.
    
    Parameters:
    - grey_coefficients: Grey coefficients for each alternative
    - normalized_matrix: The normalized decision matrix
    - weights: Weights for each criterion
    - criterion_types: List of "Benefit" or "Cost" for each criterion
    
    Returns:
    - 3N scores for each alternative
    """
    weights = as_weight_array(weights)
    values = criteria_values(normalized_matrix)
    scores = np.zeros(normalized_matrix.shape[0])
    
    for i in range(normalized_matrix.shape[0]):
        for j, criterion_type in enumerate(criterion_types):
            if criterion_type == "Benefit":
                scores[i] += weights[j] * (values[i, j] - grey_coefficients[i])
            else:  # Cost criterion
                scores[i] += weights[j] * (grey_coefficients[i] - values[i, j])
    
    return scores

def get_all_method_rankings(payoff_matrix, criterion_types):
    """
    Calculate rankings for all methods using the same input data.
    
    Parameters:
    - payoff_matrix: The decision matrix
    - criterion_types: List of "Benefit" or "Cost" for each criterion
    
    Returns:
    - Dictionary containing rankings for each method
    """
    payoff_matrix = prepare_payoff_matrix(payoff_matrix)
    rankings = {}
    alternatives = payoff_matrix['A/C'].astype(str).tolist()
    
    # PSI Method
    normalized_matrix = normalize_matrix(payoff_matrix, criterion_types)
    PSI_variables_df = calculate_PSI_variables(normalized_matrix)
    psi_weights = PSI_variables_df['psi'].to_numpy(dtype=float)
    psi_scores = normalized_matrix.iloc[:, 1:].to_numpy(dtype=float).dot(psi_weights)
    rankings['PSI'] = rank_alternatives(psi_scores, alternatives=alternatives)
    
    # MPSI-MARA Method
    normalized_matrix = normalize_matrix(payoff_matrix, criterion_types)
    variables_df = calculate_variables(normalized_matrix)
    new_matrix = calculate_new_matrix(normalized_matrix, variables_df['w'])
    set_Sj = create_set_Sj(new_matrix)
    set_Smax, set_Smin = split_sets_Smax_Smin(criterion_types, set_Sj)
    set_Tmax, set_Tmin = create_set_Tmax_Tmin(new_matrix, criterion_types)
    T_ik, T_il = calculate_T_ik_T_il(set_Tmax, set_Tmin)
    Sk = sum(set_Smax.values())
    Sl = sum(set_Smin.values())
    f_opt = optimal_alternative_function(Sk, Sl)
    alternative_functions = {alt: alternative_function(T_ik[alt], T_il[alt]) for alt in T_ik.keys()}
    def_opt_integral = calculate_definite_integral(f_opt, 0, 1)
    def_integrals = {alt: calculate_definite_integral(func, 0, 1) for alt, func in alternative_functions.items()}
    mpsi_mara_scores = [def_integrals.get(alt, np.nan) for alt in alternatives]
    rankings['MPSI-MARA'] = rank_alternatives(mpsi_mara_scores, alternatives=alternatives)
    
    # MPSI-ARLON Method
    normalized_matrix_arlon = arlon_normalize(payoff_matrix, criterion_types)
    weights = calculate_arlon_weights(normalized_matrix_arlon)
    arlon_rankings = calculate_arlon_rankings(normalized_matrix_arlon, weights)
    rankings['MPSI-ARLON'] = arlon_rankings
    
    # LOPCOW-DOBI Method
    normalized_matrix_lopcow = lopcow_normalize(payoff_matrix, criterion_types)
    weights_lopcow = calculate_lopcow_weights(normalized_matrix_lopcow)
    normalized_matrix_dobi = dobi_normalize(payoff_matrix, criterion_types)
    f_dhat_matrix = f_dhat(normalized_matrix_dobi)
    Z_L1_values = Z_i_1_v2(normalized_matrix_dobi, f_dhat_matrix, weights_lopcow, 0.8, 0.2, 2.0)
    Z_L2_values = Z_i_2_v2(normalized_matrix_dobi, f_dhat_matrix, weights_lopcow, 0.8, 0.2, 2.0)
    integrated_dobi_scores = dobi_R_i(Z_L1_values, Z_L2_values, 1.0)
    rankings['LOPCOW-DOBI'] = dobi_rank_alternatives(integrated_dobi_scores, alternatives=alternatives)
    
    # SWARA-MOORA-3NAG Method
    normalized_matrix_swara = swara_normalize(payoff_matrix, criterion_types)
    weights_swara = calculate_swara_weights(normalized_matrix_swara)
    normalized_matrix_moora = moora_normalize(payoff_matrix)
    moora_scores = calculate_moora_scores(normalized_matrix_moora, weights_swara, criterion_types)
    nag_scores = calculate_3nag_scores(moora_scores, normalized_matrix_moora, weights_swara, criterion_types)
    rankings['SWARA-MOORA-3NAG'] = rank_alternatives(nag_scores, alternatives=alternatives)
    
    # CRITIC-MOORA-3N Method
    normalized_matrix_critic = critic_normalize(payoff_matrix, criterion_types)
    weights_critic = calculate_critic_weights(normalized_matrix_critic)
    moora_scores = calculate_critic_moora_scores(normalized_matrix_critic, weights_critic, criterion_types)
    nag_scores = calculate_3n_scores(moora_scores, normalized_matrix_critic, weights_critic, criterion_types)
    rankings['CRITIC-MOORA-3N'] = rank_alternatives(nag_scores, alternatives=alternatives)
    
    # CRITIC-GRA-3N Method
    normalized_matrix_critic = critic_normalize(payoff_matrix, criterion_types)
    weights_critic_gra = calculate_critic_gra_3n_weights(normalized_matrix_critic)
    grey_coefficients = calculate_grey_coefficient(normalized_matrix_critic, weights_critic_gra, criterion_types)
    nag_scores = calculate_3n_grey_scores(grey_coefficients, normalized_matrix_critic, weights_critic_gra, criterion_types)
    rankings['CRITIC-GRA-3N'] = rank_alternatives(nag_scores, alternatives=alternatives)
    
    # CRITIC-5N-PROVAN Method
    N1 = normalize_matrix_max_min(payoff_matrix, criterion_types)
    N2 = normalize_matrix_linear_sum(payoff_matrix, criterion_types)
    N3 = normalize_matrix_with_vector(payoff_matrix, criterion_types)
    N4 = normalize_matrix_logarithmic(payoff_matrix, criterion_types)
    N5 = normalize_matrix_non_linear(payoff_matrix, criterion_types)
    normalized_mats = [N1, N2, N3, N4, N5]
    phis = [1 / len(normalized_mats)] * len(normalized_mats)
    eta_agg_df = aczel_alsina_provan_matrix(normalized_mats, phis=phis, xi=3.0)
    result_ranking, _, _ = provan_ranking(eta_agg_df, criterion_types)
    provan_ranking_df = result_ranking[['A/C', 'Score']].rename(columns={'A/C': 'Alternative'})
    rankings['CRITIC-5N-PROVAN'] = provan_ranking_df

    # MPSI-WASPAS Method
    normalized_matrix = mpsi_waspas_normalize(payoff_matrix, criterion_types)
    weights = calculate_mpsi_waspas_weights(normalized_matrix)
    waspas_rankings = calculate_mpsi_waspas_rankings(normalized_matrix, weights, criterion_types, lambda_value=0.5)
    rankings['MPSI-WASPAS'] = waspas_rankings
    
    return rankings

def create_comparison_graph(rankings):
    """
    Create a line graph comparing rankings across all methods.
    """
    plot_data = []
    for method, ranking_df in rankings.items():
        for idx, row in ranking_df.iterrows():
            plot_data.append({
                'Method': method,
                'Alternative': row['Alternative'],
                'Rank': idx + 1
            })

    df_plot = pd.DataFrame(plot_data)

    df_plot['Alternative_Num'] = (
        df_plot['Alternative']
        .astype(str)
        .str.extract(r'(\d+)', expand=False)
    )
    df_plot['Alternative_Num'] = pd.to_numeric(df_plot['Alternative_Num'], errors='coerce')
    df_plot = df_plot.sort_values(['Alternative_Num', 'Alternative'])

    # ponytail: colorblind-safe, grayscale-distinguishable palette (Wong 2011) —
    # avoids CRITIC-MOORA-3N/CRITIC-GRA-3N collapsing to the same gray in print
    palette = ['#000000', '#E69F00', '#56B4E9', '#009E73', '#D55E00', '#CC79A7', '#0072B2', '#F0E442']

    fig = px.line(
        df_plot,
        x='Alternative',
        y='Rank',
        color='Method',
        title='Method Comparison: Rankings of Alternatives',
        labels={'Rank': 'Ranking Position', 'Alternative': 'Alternative'},
        markers=True,
        color_discrete_sequence=palette
    )

    categoryarray = (
        df_plot[['Alternative', 'Alternative_Num']]
        .drop_duplicates()
        .sort_values(['Alternative_Num', 'Alternative'])
        ['Alternative']
        .tolist()
    )
    fig.update_layout(
        yaxis=dict(
            title='Ranking Position',
            tickmode='linear',
            tick0=1,
            dtick=1,
            autorange='reversed'
        ),
        xaxis=dict(
            title='Alternative',
            categoryorder='array',
            categoryarray=categoryarray
        ),
        showlegend=True,
        legend_title='Method',
        # ponytail: fixed export size + right margin so the legend never clips;
        # bump width further if you add a 7th/8th method to the comparison
        width=950,
        height=520,
        margin=dict(l=60, r=200, t=60, b=60),
        legend=dict(x=1.02, xanchor='left', y=1, yanchor='top', font=dict(size=11))
    )

    return fig

def mpsi_waspas_normalize(matrix, criterion_types):
    """
    Normalize the decision matrix using MPSI-WASPAS method.
    
    Parameters:
    - matrix: The decision matrix (alternatives x criteria)
    - criterion_types: List of "Benefit" or "Cost" for each criterion
    
    Returns:
    - Normalized matrix
    """
    normalized_matrix = matrix.copy()
    
    for j, criterion_type in enumerate(criterion_types):
        if criterion_type == "Benefit":
            col_max = matrix.iloc[:, j+1].max()
            normalized_matrix.iloc[:, j+1] = matrix.iloc[:, j+1] / col_max
        else:  # Cost criterion
            col_min = matrix.iloc[:, j+1].min()
            normalized_matrix.iloc[:, j+1] = col_min / matrix.iloc[:, j+1]
    
    return normalized_matrix

def calculate_mpsi_waspas_weights(normalized_matrix):
    """
    Calculate weights using MPSI-WASPAS method.
    
    Parameters:
    - normalized_matrix: The normalized decision matrix
    
    Returns:
    - Weights for each criterion
    """
    # Calculate mean value for each criterion
    mean_values = normalized_matrix.iloc[:, 1:].mean()
    
    # Calculate standard deviation for each criterion
    std_dev = normalized_matrix.iloc[:, 1:].std()
    
    # Calculate weights using MPSI formula
    weights = std_dev / (mean_values + std_dev)
    
    # Normalize weights
    weights = weights / weights.sum()
    
    return as_weight_array(weights)

def calculate_waspas_scores(normalized_matrix, weights, criterion_types, lambda_value=0.5):
    """
    Calculate WASPAS scores for each alternative.
    
    Parameters:
    - normalized_matrix: The normalized decision matrix
    - weights: Weights for each criterion
    - criterion_types: List of "Benefit" or "Cost" for each criterion
    - lambda_value: Weight parameter for WASPAS (default: 0.5)
    
    Returns:
    - WASPAS scores for each alternative
    """
    weights = as_weight_array(weights)
    values = criteria_values(normalized_matrix)

    # Calculate WSM scores
    wsm_scores = np.zeros(normalized_matrix.shape[0])
    for i in range(normalized_matrix.shape[0]):
        for j, criterion_type in enumerate(criterion_types):
            wsm_scores[i] += weights[j] * values[i, j]
    
    # Calculate WPM scores
    wpm_scores = np.ones(normalized_matrix.shape[0])
    for i in range(normalized_matrix.shape[0]):
        for j, criterion_type in enumerate(criterion_types):
            wpm_scores[i] *= values[i, j] ** weights[j]
    
    # Calculate WASPAS scores
    waspas_scores = lambda_value * wsm_scores + (1 - lambda_value) * wpm_scores
    
    return waspas_scores

def calculate_mpsi_waspas_rankings(normalized_matrix, weights, criterion_types, lambda_value=0.5, alternatives=None):
    """
    Calculate final rankings using MPSI-WASPAS method.
    
    Parameters:
    - normalized_matrix: The normalized decision matrix
    - weights: Weights for each criterion
    - criterion_types: List of "Benefit" or "Cost" for each criterion
    - lambda_value: Weight parameter for WASPAS (default: 0.5)
    
    Returns:
    - DataFrame with alternatives and their rankings
    """
    scores = calculate_waspas_scores(normalized_matrix, weights, criterion_types, lambda_value)
    
    if alternatives is None:
        alternatives = normalized_matrix['A/C'].astype(str).tolist()

    rankings = pd.DataFrame({
        'Alternative': list(alternatives),
        'Score': scores
    })
    
    # Sort by score in descending order
    rankings = rankings.sort_values(by='Score', ascending=False).reset_index(drop=True)
    
    return rankings

def calculate_kendall_tau_correlations(rankings, selected_methods):
    """
    Calculate Kendall Tau correlation between all pairs of selected methods.
    
    Parameters:
    - rankings: Dictionary containing rankings for each method
    - selected_methods: List of methods to compare
    
    Returns:
    - List of dictionaries containing method pairs and their Kendall Tau correlation
    """
    correlations = []
    
    # Get all possible pairs of methods
    method_pairs = list(itertools.combinations(selected_methods, 2))
    
    for method1, method2 in method_pairs:
        # Get rankings for both methods and ensure we use the same alternatives
        alternatives = set(rankings[method1]['Alternative']).intersection(set(rankings[method2]['Alternative']))
        
        # Create rank arrays for common alternatives
        rank1 = []
        rank2 = []
        
        # For each alternative, get its rank (index + 1) in each method
        for alt in alternatives:
            rank1.append(rankings[method1][rankings[method1]['Alternative'] == alt].index[0] + 1)
            rank2.append(rankings[method2][rankings[method2]['Alternative'] == alt].index[0] + 1)
        
        # Calculate Kendall Tau correlation only if we have alternatives to compare
        if rank1 and rank2:
            tau, _ = kendalltau(rank1, rank2)
            
            # Add to correlations list
            correlations.append({
                'Methods': f'{method1}, {method2}',
                'Kendall Tau': tau
            })
    
    return correlations

def smaa_analysis(payoff_matrix: pd.DataFrame, criterion_types: list, num_simulations: int = 10000):
    """
    Perform SMAA and SMAA-2 analysis.

    Args:
        payoff_matrix (pd.DataFrame): Alternatives × Criteria matrix.
        criterion_types (list of str): List of "Benefit"/"Cost" for each criterion.
        num_simulations (int): Number of Monte Carlo iterations.

    Returns:
        Tuple of DataFrames: (rank_acceptability, winning_index, central_weights)
    """
    alternatives = payoff_matrix['A/C'].values
    criteria_names = payoff_matrix.columns[1:]  # Skip 'A/C' column
    matrix = payoff_matrix.iloc[:, 1:].values  # Skip 'A/C' column
    num_alternatives, num_criteria = matrix.shape

    # Normalize the matrix
    normalized_matrix = np.zeros_like(matrix, dtype=float)
    for j, criterion_type in enumerate(criterion_types):
        col = matrix[:, j]
        if criterion_type.strip().lower() == 'benefit':
            normalized_matrix[:, j] = (col - col.min()) / (col.max() - col.min())
        else:  # Cost criterion
            normalized_matrix[:, j] = (col.max() - col) / (col.max() - col.min())

    # Monte Carlo simulation
    rng = default_rng()
    rank_counts = np.zeros((num_alternatives, num_alternatives))
    winning_counts = np.zeros(num_alternatives)
    central_weights = np.zeros((num_alternatives, num_criteria))
    winning_weight_sums = np.zeros((num_alternatives, num_criteria))

    for _ in range(num_simulations):
        weights = rng.dirichlet(np.ones(num_criteria))
        scores = normalized_matrix @ weights
        ranked_indices = np.argsort(-scores)

        for rank, alt_index in enumerate(ranked_indices):
            rank_counts[alt_index, rank] += 1

        best_alt = ranked_indices[0]
        winning_counts[best_alt] += 1
        winning_weight_sums[best_alt] += weights

    rank_acceptability = rank_counts / num_simulations
    winning_index = winning_counts / num_simulations
    nonzero_winners = winning_counts != 0
    central_weights[nonzero_winners] = (winning_weight_sums[nonzero_winners].T / winning_counts[nonzero_winners]).T

    rank_df = pd.DataFrame(rank_acceptability, index=alternatives,
                          columns=[f"Rank {i+1}" for i in range(num_alternatives)])
    win_df = pd.DataFrame(winning_index, index=alternatives, columns=["Winning Index"])
    cwv_df = pd.DataFrame(central_weights, index=alternatives, columns=criteria_names)

    return rank_df, win_df, cwv_df

def main():
    menu = ["Home", "PSI", "MPSI-MARA", "MPSI-ARLON", "LOPCOW-DOBI", "SWARA-MOORA-3NAG", "CRITIC-MOORA-3N", "CRITIC-GRA-3N", "CRITIC-5N-PROVAN", "MPSI-WASPAS", "Method Comparison", "About"]

    choice = st.sidebar.selectbox("Menu", menu)

    if choice == "Home":
        st.header("Home")
        st.subheader("MEGA-MCDA: Multicriteria Decision Analysis Calculator")
        st.write("Welcome to MEGA-MCDA, a comprehensive calculator for multiple Multicriteria Decision Analysis (MCDA) methods.")
        st.write("This application includes the following methods:")
        st.write("1. PSI (Preference Selection Index) - A method for ranking alternatives based on preference selection")
        st.write("2. MPSI-MARA - A hybrid method combining MPSI with MARA for improved decision making")
        st.write("3. MPSI-ARLON - A hybrid method combining MPSI with ARLON for enhanced decision analysis")
        st.write("4. LOPCOW-DOBI - A hybrid method combining LOPCOW with DOBI for comprehensive decision evaluation")
        st.write("5. SWARA-MOORA-3NAG - A hybrid method combining SWARA, MOORA, and 3NAG for advanced decision analysis")
        st.write("6. CRITIC-MOORA-3N - A hybrid method combining CRITIC, MOORA, and 3N for objective decision analysis")
        st.write("7. CRITIC-GRA-3N - A hybrid method combining CRITIC, GRA, and 3N for objective decision analysis")
        st.write("8. CRITIC-5N-PROVAN - A hybrid method combining CRITIC with the 5N-PROVAN aggregation")
        st.write("9. MPSI-WASPAS - A hybrid method combining MPSI and WASPAS for multi-criteria decision analysis")
        st.write("To use this Calculator:")
        st.write("1. Select the desired method from the sidebar menu")
        st.write("2. Choose between manual input or uploading an Excel file")
        st.write("3. Define your alternatives and criteria")
        st.write("4. Specify whether each criterion is of benefit (more is better) or cost (less is better)")
        st.write("5. Input your data and get the results")

    elif choice == "PSI":
        st.title("PSI Calculator")
        data_source = st.radio("How would you like to input data?", ["Manual Input", "Upload Excel"])
        
        if data_source == "Upload Excel":
            st.write("Download the template to fill out the data:")
            download_template()  # Excel template download button
            uploaded_file = st.file_uploader("Upload Excel file", type=["xlsx"])
            if uploaded_file:
                payoff_matrix, criterion_types, num_alternatives, num_criteria = read_excel(uploaded_file)
                st.dataframe(payoff_matrix)
        else:
            payoff_matrix, criterion_types = get_payoff_matrix()

        normalized_matrix = normalize_matrix(payoff_matrix, criterion_types)
        st.subheader("Normalized Matrix:")
        st.dataframe(normalized_matrix)

        PSI_variables_df = calculate_PSI_variables(normalized_matrix)
        st.subheader("Calculated Variables:")
        st.dataframe(PSI_variables_df)

        # Plot the PSI weights
        fig = px.bar(PSI_variables_df, x=PSI_variables_df.index, y='psi', labels={'index': 'Criteria', 'psi': 'PSI Weight'}, title='PSI Weights for Criteria')
        st.plotly_chart(fig)

    elif choice == "MPSI-MARA":
        st.title("MPSI-MARA Hybrid Method MCDA Calculator")
        data_source = st.radio("How would you like to input data?", ["Manual Input", "Upload Excel"])

        if data_source == "Upload Excel":
            st.write("Download the template to fill out the data:")
            download_template()  # Add the download button for the Excel template
            uploaded_file = st.file_uploader("Upload Excel file", type=["xlsx"])
            if uploaded_file:
                payoff_matrix, criterion_types, num_alternatives, num_criteria = read_excel(uploaded_file)
                st.dataframe(payoff_matrix)
        else:
            payoff_matrix, criterion_types = get_payoff_matrix()

        # Normalize the data
        normalized_matrix = normalize_matrix(payoff_matrix, criterion_types)
        st.subheader("Normalized Matrix:")
        st.dataframe(normalized_matrix)

        # Calculate the variables (v, p, w)
        variables_df = calculate_variables(normalized_matrix)
        st.subheader("Calculated Variables (v, p, w):")
        st.dataframe(variables_df)

        # Calculate the new matrix
        new_matrix = calculate_new_matrix(normalized_matrix, variables_df['w'])
        st.subheader("New Matrix:")
        st.dataframe(new_matrix)

        # Calculate the sets Sj, Smax, Smin
        set_Sj = create_set_Sj(new_matrix)
        set_Smax, set_Smin = split_sets_Smax_Smin(criterion_types, set_Sj)
        st.subheader("Set S_j (Transposed):")
        st.dataframe(pd.DataFrame(set_Sj, index=['Value']))  # Display transposed dataframe

        # Calculate T_ik and T_il
        set_Tmax, set_Tmin = create_set_Tmax_Tmin(new_matrix, criterion_types)
        T_ik, T_il = calculate_T_ik_T_il(set_Tmax, set_Tmin)
        
        # Display T_ik and T_il
        st.subheader("T_ik for each alternative:")
        st.dataframe(pd.DataFrame(T_ik, index=['Value']))
        st.subheader("T_il for each alternative:")
        st.dataframe(pd.DataFrame(T_il, index=['Value']))

        # Calculate the optimal alternative function
        Sk = sum(set_Smax.values())
        Sl = sum(set_Smin.values())
        st.subheader(f"Optimal Alternative Function: Sk={Sk}, Sl={Sl}")
        f_opt = optimal_alternative_function(Sk, Sl)
        st.write(f"f_opt(x) = ({Sl} - {Sk}) * x + {Sk}")

        # Calculate the alternative functions for each alternative
        alternative_functions = {alt: alternative_function(T_ik[alt], T_il[alt]) for alt in T_ik.keys()}
        st.subheader("Alternative Functions:")
        for alt, func in alternative_functions.items():
            st.write(f"f_{alt}(x) = ({T_il[alt]} - {T_ik[alt]}) * x + {T_ik[alt]}")

        # Calculate definite integrals
        def_opt_integral = calculate_definite_integral(f_opt, 0, 1)
        st.subheader("Definite Integral of Optimal Alternative Function:")
        st.write(def_opt_integral)

        def_integrals = {alt: calculate_definite_integral(func, 0, 1) for alt, func in alternative_functions.items()}
        st.subheader("Definite Integrals of Alternative Functions:")
        for alt, integral in def_integrals.items():
            st.write(f"Definite Integral of f_{alt}(x): {integral}")

        # Calculate differences and rank alternatives
        ranked_alternatives = sorted(def_integrals, key=lambda alt: def_opt_integral - def_integrals[alt])
        st.subheader("Ranking of Alternatives:")
        for rank, alt in enumerate(ranked_alternatives, 1):
            st.write(f"Rank {rank}: Alternative {alt}")

    elif choice == "MPSI-ARLON":
        st.title("MPSI-ARLON Method MCDA Calculator")
        data_source = st.radio("How would you like to input data?", ["Manual Input", "Upload Excel"])

        if data_source == "Upload Excel":
            st.write("Download the template to fill out the data:")
            download_template()  # Add the download button for the Excel template
            uploaded_file = st.file_uploader("Upload Excel file", type=["xlsx"])
            if uploaded_file:
                payoff_matrix, criterion_types, num_alternatives, num_criteria = read_excel(uploaded_file)
                st.dataframe(payoff_matrix)
        else:
            payoff_matrix, criterion_types = get_payoff_matrix()

        # Normalize using ARLON-specific normalization
        normalized_matrix_arlon = arlon_normalize(payoff_matrix, criterion_types)
        st.subheader("Normalized Matrix (ARLON):")
        st.dataframe(normalized_matrix_arlon)

        # Calculate weights and rankings
        weights = calculate_arlon_weights(normalized_matrix_arlon)
        st.subheader("Criterion Weights (ARLON):")
        st.dataframe(pd.DataFrame(weights).transpose())  # Display weights as a dataframe

        rankings = calculate_arlon_rankings(normalized_matrix_arlon, weights)
        st.subheader("Rankings (ARLON):")
        st.dataframe(rankings)

    elif choice == "LOPCOW-DOBI":
        st.title("LOPCOW-DOBI Method MCDA Calculator")
        data_source = st.radio("How would you like to input data?", ["Manual Input", "Upload Excel"])

        if data_source == "Upload Excel":
            st.write("Download the template to fill out the data:")
            download_template()  # Template download button for Excel
            uploaded_file = st.file_uploader("Upload Excel file", type=["xlsx"])
            if uploaded_file:
                payoff_matrix, criterion_types, num_alternatives, num_criteria = read_excel(uploaded_file)
                st.dataframe(payoff_matrix)
        else:
            payoff_matrix, criterion_types = get_payoff_matrix()

        # Normalize the matrix for the LOPCOW method
        normalized_matrix_lopcow = lopcow_normalize(payoff_matrix, criterion_types)
        st.subheader("Normalized Matrix (LOPCOW):")
        st.dataframe(normalized_matrix_lopcow)

        # Calculate weights using the LOPCOW method
        weights_lopcow = calculate_lopcow_weights(normalized_matrix_lopcow)
        st.subheader("Criterion Weights (LOPCOW):")
        st.dataframe(pd.DataFrame(weights_lopcow, columns=['Weights']).transpose())

        # --- DOBI Method Parameters ---
        st.subheader("DOBI Parameters")
        psi1 = st.number_input("Psi 1", min_value=0.0, value=0.8, step=0.1, key='psi1_input')
        psi2 = st.number_input("Psi 2", min_value=0.0, value=0.2, step=0.1, key='psi2_input')
        zeta = st.number_input("Zeta", min_value=0.0, value=2.0, step=0.1, key='zeta_input')  # Ensure Zeta >= 0
        delta = st.number_input("Delta (for integrated value)", min_value=0.0, value=1.0, step=0.1, key='delta_input')

        # --- Normalize the matrix for DOBI ---
        normalized_matrix_dobi = dobi_normalize(payoff_matrix, criterion_types)
        st.subheader("Normalized Matrix (DOBI):")
        st.dataframe(normalized_matrix_dobi)

        # --- Display f_dhat using LaTeX ---
        st.subheader("f(dhat) Matrix:")
        st.latex(r'f(\hat{\partial}) = \frac{\hat{\partial}_{ij}}{\sum \hat{\partial}_{ij}}')  # Display LaTeX formula

        # --- Calculate and display the f_dhat matrix ---
        f_dhat_matrix = f_dhat(normalized_matrix_dobi)
        st.dataframe(f_dhat_matrix)

        # --- Calculate the Z_L1 function from DOBI ---
        #st.subheader("Z_L1 Values (Updated Function)")

        # Call the updated Z_i_1_v2 function to calculate the Z_L1 values
        Z_L1_values = Z_i_1_v2(normalized_matrix_dobi, f_dhat_matrix, weights_lopcow, psi1, psi2, zeta)

        # Display Z_L1 values
        st.subheader("Z_L1 Values:")
        st.dataframe(pd.DataFrame(Z_L1_values, columns=["Z_L1"]))

        # --- Calculate the Z_L2 function from DOBI (using new Z_i_2_v2 function) ---
        #st.subheader("Z_L2 Values (Updated Function)")

        # Call the updated Z_i_2_v2 function to calculate the Z_L2 values
        Z_L2_values = Z_i_2_v2(normalized_matrix_dobi, f_dhat_matrix, weights_lopcow, psi1, psi2, zeta)

        # Display Z_L2 values
        st.subheader("Z_L2 Values:")
        st.dataframe(pd.DataFrame(Z_L2_values, columns=["Z_L2"]))

        # --- Calculate the integrated DOBI scores ---
        #st.subheader("Integrated DOBI Scores")

        # Use the Z_L1 and Z_L2 values to calculate the final integrated value R_i
        integrated_dobi_scores = dobi_R_i(Z_L1_values, Z_L2_values, delta)

        # Display the integrated scores
        st.subheader("Integrated DOBI Scores:")
        st.dataframe(pd.DataFrame(integrated_dobi_scores, columns=["Integrated Score"]))

        # --- Rank Alternatives based on the integrated scores ---
        rankings_dobi = dobi_rank_alternatives(integrated_dobi_scores)
        st.subheader("Rankings (DOBI):")
        st.dataframe(rankings_dobi)

    elif choice == "SWARA-MOORA-3NAG":
        st.title("SWARA-MOORA-3NAG Method MCDA Calculator")
        data_source = st.radio("How would you like to input data?", ["Manual Input", "Upload Excel"])

        if data_source == "Upload Excel":
            st.write("Download the template to fill out the data:")
            download_template()
            uploaded_file = st.file_uploader("Upload Excel file", type=["xlsx"])
            if uploaded_file:
                payoff_matrix, criterion_types, num_alternatives, num_criteria = read_excel(uploaded_file)
                st.dataframe(payoff_matrix)
        else:
            payoff_matrix, criterion_types = get_payoff_matrix()

        # Step 1: SWARA Normalization
        normalized_matrix_swara = swara_normalize(payoff_matrix, criterion_types)
        st.subheader("Normalized Matrix (SWARA):")
        st.dataframe(normalized_matrix_swara)

        # Step 2: Calculate SWARA Weights
        weights_swara = calculate_swara_weights(normalized_matrix_swara)
        st.subheader("Criterion Weights (SWARA):")
        st.dataframe(pd.DataFrame(weights_swara).transpose())

        # Step 3: MOORA Normalization
        normalized_matrix_moora = moora_normalize(payoff_matrix)
        st.subheader("Normalized Matrix (MOORA):")
        st.dataframe(normalized_matrix_moora)

        # Step 4: Calculate MOORA Scores
        moora_scores = calculate_moora_scores(normalized_matrix_moora, weights_swara, criterion_types)
        st.subheader("MOORA Scores:")
        st.dataframe(pd.DataFrame(moora_scores, columns=['MOORA Score']))

        # Step 5: Calculate 3NAG Scores
        nag_scores = calculate_3nag_scores(moora_scores, normalized_matrix_moora, weights_swara, criterion_types)
        st.subheader("3NAG Scores:")
        st.dataframe(pd.DataFrame(nag_scores, columns=['3NAG Score']))

        # Step 6: Final Rankings
        final_rankings = rank_alternatives(nag_scores)
        st.subheader("Final Rankings:")
        st.dataframe(final_rankings)

        # Plot the rankings
        fig = px.bar(
            final_rankings,
            x='Alternative',
            y='Score',
            title='Final Rankings of Alternatives',
            labels={'Score': '3NAG Score'}
        )
        fig.update_layout(xaxis_title_text='Alternative', yaxis_title_text='3NAG Score')
        st.plotly_chart(fig)

    elif choice == "CRITIC-MOORA-3N":
        st.title("CRITIC-MOORA-3N Method MCDA Calculator")
        data_source = st.radio("How would you like to input data?", ["Manual Input", "Upload Excel"])

        if data_source == "Upload Excel":
            st.write("Download the template to fill out the data:")
            download_template()
            uploaded_file = st.file_uploader("Upload Excel file", type=["xlsx"])
            if uploaded_file:
                payoff_matrix, criterion_types, num_alternatives, num_criteria = read_excel(uploaded_file)
                st.dataframe(payoff_matrix)
        else:
            payoff_matrix, criterion_types = get_payoff_matrix()

        # Step 1: CRITIC Normalization
        normalized_matrix_critic = critic_normalize(payoff_matrix, criterion_types)
        st.subheader("Normalized Matrix (CRITIC):")
        st.dataframe(normalized_matrix_critic)

        # Step 2: Calculate CRITIC Weights
        weights_critic = calculate_critic_weights(normalized_matrix_critic)
        st.subheader("Criterion Weights (CRITIC):")
        st.dataframe(pd.DataFrame(weights_critic).transpose())

        # Step 3: Calculate MOORA Scores
        moora_scores = calculate_critic_moora_scores(normalized_matrix_critic, weights_critic, criterion_types)
        st.subheader("MOORA Scores:")
        st.dataframe(pd.DataFrame(moora_scores, columns=['MOORA Score']))

        # Step 4: Calculate 3N Scores
        nag_scores = calculate_3n_scores(moora_scores, normalized_matrix_critic, weights_critic, criterion_types)
        st.subheader("3N Scores:")
        st.dataframe(pd.DataFrame(nag_scores, columns=['3N Score']))

        # Step 5: Final Rankings
        final_rankings = rank_alternatives(nag_scores)
        st.subheader("Final Rankings:")
        st.dataframe(final_rankings)

        # Plot the rankings
        fig = px.bar(
            final_rankings,
            x='Alternative',
            y='Score',
            title='Final Rankings of Alternatives',
            labels={'Score': '3N Score'}
        )
        fig.update_layout(xaxis_title_text='Alternative', yaxis_title_text='3N Score')
        st.plotly_chart(fig)

    elif choice == "CRITIC-GRA-3N":
        st.title("CRITIC-GRA-3N Method MCDA Calculator")
        data_source = st.radio("How would you like to input data?", ["Manual Input", "Upload Excel"])

        if data_source == "Upload Excel":
            st.write("Download the template to fill out the data:")
            download_template()
            uploaded_file = st.file_uploader("Upload Excel file", type=["xlsx"])
            if uploaded_file:
                payoff_matrix, criterion_types, num_alternatives, num_criteria = read_excel(uploaded_file)
                st.dataframe(payoff_matrix)
        else:
            payoff_matrix, criterion_types = get_payoff_matrix()

        # Step 1: CRITIC Normalization
        normalized_matrix_critic = critic_normalize(payoff_matrix, criterion_types)
        st.subheader("Normalized Matrix (CRITIC):")
        st.dataframe(normalized_matrix_critic)

        # Step 2: Calculate CRITIC-GRA-3N Weights
        weights_critic_gra = calculate_critic_gra_3n_weights(normalized_matrix_critic)
        st.subheader("Criterion Weights (CRITIC-GRA-3N):")
        st.dataframe(pd.DataFrame(weights_critic_gra).transpose())

        # Step 3: Calculate Grey Coefficients
        grey_coefficients = calculate_grey_coefficient(normalized_matrix_critic, weights_critic_gra, criterion_types)
        st.subheader("Grey Coefficients:")
        st.dataframe(pd.DataFrame(grey_coefficients, columns=['Grey Coefficient']))

        # Step 4: Calculate 3N Scores
        nag_scores = calculate_3n_grey_scores(grey_coefficients, normalized_matrix_critic, weights_critic_gra, criterion_types)
        st.subheader("3N Scores:")
        st.dataframe(pd.DataFrame(nag_scores, columns=['3N Score']))

        # Step 5: Final Rankings
        final_rankings = rank_alternatives(nag_scores)
        st.subheader("Final Rankings:")
        st.dataframe(final_rankings)

        # Plot the rankings
        fig = px.bar(
            final_rankings,
            x='Alternative',
            y='Score',
            title='Final Rankings of Alternatives',
            labels={'Score': '3N Score'}
        )
        fig.update_layout(xaxis_title_text='Alternative', yaxis_title_text='3N Score')
        st.plotly_chart(fig)

    elif choice == "CRITIC-5N-PROVAN":
        st.title("CRITIC-5N-PROVAN Method MCDA Calculator")
        data_source = st.radio("How would you like to input data?", ["Manual Input", "Upload Excel"])

        payoff_matrix = None
        criterion_types = None

        if data_source == "Upload Excel":
            st.write("Download the template to fill out the data:")
            download_template()
            uploaded_file = st.file_uploader("Upload Excel file", type=["xlsx"])
            if uploaded_file:
                payoff_matrix, criterion_types, num_alternatives, num_criteria = read_excel(uploaded_file)
                st.dataframe(payoff_matrix)
        else:
            payoff_matrix, criterion_types = get_payoff_matrix()

        if payoff_matrix is not None and criterion_types is not None:
            xi_param = st.number_input("Xi (ξ) parameter", min_value=0.1, value=3.0, step=0.1)
            try:
                with st.spinner("Calculating CRITIC-5N-PROVAN..."):
                    N1 = normalize_matrix_max_min(payoff_matrix, criterion_types)
                    N2 = normalize_matrix_linear_sum(payoff_matrix, criterion_types)
                    N3 = normalize_matrix_with_vector(payoff_matrix, criterion_types)
                    N4 = normalize_matrix_logarithmic(payoff_matrix, criterion_types)
                    N5 = normalize_matrix_non_linear(payoff_matrix, criterion_types)
                    normalized_mats = [N1, N2, N3, N4, N5]
                    phis = [1 / len(normalized_mats)] * len(normalized_mats)
                    eta_agg_df = aczel_alsina_provan_matrix(normalized_mats, phis=phis, xi=xi_param)
                    result_ranking, w_critic, theta_df = provan_ranking(eta_agg_df, criterion_types)

                st.subheader("Aggregated Matrix (η_ij)")
                st.dataframe(eta_agg_df)

                st.subheader("CRITIC Weights (w_j)")
                st.dataframe(pd.DataFrame(w_critic, columns=["Weight"]).transpose())

                st.subheader("Weighted Matrix (ϑ_ij)")
                st.dataframe(theta_df)

                st.subheader("PROVAN Ranking")
                st.dataframe(result_ranking)
            except ValueError as e:
                st.error(str(e))
        else:
            st.info("Please input your data using either manual input or by uploading an Excel file to see the results.")

    elif choice == "MPSI-WASPAS":
        st.title("MPSI-WASPAS Method MCDA Calculator")
        data_source = st.radio("How would you like to input data?", ["Manual Input", "Upload Excel"])

        # Initialize variables
        payoff_matrix = None
        criterion_types = None

        if data_source == "Upload Excel":
            st.write("Download the template to fill out the data:")
            download_template()
            uploaded_file = st.file_uploader("Upload Excel file", type=["xlsx"])
            if uploaded_file:
                payoff_matrix, criterion_types, num_alternatives, num_criteria = read_excel(uploaded_file)
                st.dataframe(payoff_matrix)
        else:
            payoff_matrix, criterion_types = get_payoff_matrix()

        # Only proceed if we have valid data
        if payoff_matrix is not None and criterion_types is not None:
            # Step 1: MPSI-WASPAS Normalization
            normalized_matrix = mpsi_waspas_normalize(payoff_matrix, criterion_types)
            st.subheader("Normalized Matrix (MPSI-WASPAS):")
            st.dataframe(normalized_matrix)

            # Step 2: Calculate MPSI-WASPAS Weights
            weights = calculate_mpsi_waspas_weights(normalized_matrix)
            st.subheader("Criterion Weights (MPSI-WASPAS):")
            st.dataframe(pd.DataFrame(weights).transpose())

            # Step 3: Calculate WASPAS Scores
            scores = calculate_waspas_scores(normalized_matrix, weights, criterion_types, lambda_value=0.5)
            st.subheader("WASPAS Scores:")
            st.dataframe(pd.DataFrame(scores, columns=['WASPAS Score']))

            # Step 4: Set lambda value
            lambda_value = st.slider("Lambda Value", min_value=0.0, max_value=1.0, value=0.5, step=0.1)

            # Step 5: Final Rankings
            rankings = calculate_mpsi_waspas_rankings(normalized_matrix, weights, criterion_types, lambda_value)
            st.subheader("Final Rankings:")
            st.dataframe(rankings)

            # Plot the rankings
            fig = px.bar(
                rankings,
                x='Alternative',
                y='Score',
                title='Final Rankings of Alternatives',
                labels={'Score': 'WASPAS Score'}
            )
            fig.update_layout(xaxis_title_text='Alternative', yaxis_title_text='WASPAS Score')
            st.plotly_chart(fig)
        else:
            st.info("Please input your data using either manual input or by uploading an Excel file to see the results.")

    elif choice == "Method Comparison":
        st.title("Method Comparison")
        st.write("This section compares the rankings obtained from all methods using the same input data.")
        
        data_source = st.radio("How would you like to input data?", ["Manual Input", "Upload Excel"])
        
        # Initialize variables
        payoff_matrix = None
        criterion_types = None
        
        if data_source == "Upload Excel":
            st.write("Download the template to fill out the data:")
            download_template()
            uploaded_file = st.file_uploader("Upload Excel file", type=["xlsx"])
            if uploaded_file:
                payoff_matrix, criterion_types, num_alternatives, num_criteria = read_excel(uploaded_file)
                st.dataframe(payoff_matrix)
        else:
            payoff_matrix, criterion_types = get_payoff_matrix()
        
        # Only proceed if we have valid data
        if payoff_matrix is not None and criterion_types is not None:
            # Calculate rankings for all methods
            with st.spinner('Calculating rankings for all methods...'):
                rankings = get_all_method_rankings(payoff_matrix, criterion_types)
            
            # Create method selection widget
            available_methods = list(rankings.keys())
            selected_methods = st.multiselect(
                "Select methods to compare:",
                options=available_methods,
                default=available_methods,
                help="Choose which methods you want to display in the comparison graph"
            )
            
            if selected_methods:
                # Filter rankings to include only selected methods
                filtered_rankings = {method: rankings[method] for method in selected_methods}
                
                # Create and display the comparison graph
                st.subheader("Ranking Comparison Graph")
                fig = create_comparison_graph(filtered_rankings)
                st.plotly_chart(fig, use_container_width=True)
                
                # Calculate and display Kendall Tau correlations
                if len(selected_methods) >= 2:
                    st.subheader("Kendall Tau Correlation Analysis")
                    correlations = calculate_kendall_tau_correlations(filtered_rankings, selected_methods)
                    
                    # Create horizontal bar plot for Kendall Tau correlations
                    fig_kendall = go.Figure()
                    
                    # Add bars
                    fig_kendall.add_trace(go.Bar(
                        y=[corr['Methods'] for corr in correlations],
                        x=[corr['Kendall Tau'] for corr in correlations],
                        orientation='h',
                        marker_color='lightblue'
                    ))
                    
                    # Update layout
                    fig_kendall.update_layout(
                        title='Kendall Tau Values',
                        xaxis_title='Kendall Tau Value',
                        yaxis_title='Rankings',
                        height=max(300, len(correlations) * 40),  # Dynamic height based on number of correlations
                        margin=dict(l=20, r=20, t=40, b=20),
                        yaxis={'categoryorder': 'total ascending'}
                    )
                    
                    st.plotly_chart(fig_kendall, use_container_width=True)
                    
                    # Display correlation values in a table
                    st.subheader("Kendall Tau Correlation Values")
                    correlation_df = pd.DataFrame(correlations)
                    st.dataframe(correlation_df)
                
                # SMAA Analysis Section
                st.subheader("SMAA Analysis")
                
                # SMAA Parameters
                col1, col2 = st.columns(2)
                with col1:
                    num_simulations = st.number_input(
                        "Number of Monte Carlo Simulations",
                        min_value=1000,
                        max_value=100000,
                        value=10000,
                        step=1000
                    )
                with col2:
                    show_rank_acceptability = st.checkbox("Show Rank Acceptability Matrix", value=True)
                    show_winning_index = st.checkbox("Show Winning Index", value=True)
                    show_central_weights = st.checkbox("Show Central Weight Vectors", value=True)
                
                # Perform SMAA analysis
                with st.spinner('Performing SMAA analysis...'):
                    rank_df, win_df, cwv_df = smaa_analysis(payoff_matrix, criterion_types, num_simulations)
                
                # Display results based on user selection
                if show_rank_acceptability:
                    st.subheader("Rank Acceptability Matrix")
                    st.write("Probability of each alternative achieving each rank")
                    fig_rank = px.imshow(
                        rank_df,
                        labels=dict(x="Rank", y="Alternative", color="Probability"),
                        aspect="auto"
                    )
                    fig_rank.update_layout(
                        title="Rank Acceptability Matrix",
                        xaxis_title="Rank",
                        yaxis_title="Alternative"
                    )
                    st.plotly_chart(fig_rank, use_container_width=True)
                    st.dataframe(rank_df)
                
                if show_winning_index:
                    st.subheader("Winning Index")
                    st.write("Probability of each alternative being the best")
                    fig_win = px.bar(
                        win_df,
                        x=win_df.index,
                        y="Winning Index",
                        title="Winning Index",
                        labels={"x": "Alternative", "y": "Probability"}
                    )
                    st.plotly_chart(fig_win, use_container_width=True)
                    st.dataframe(win_df)
                
                if show_central_weights:
                    st.subheader("Central Weight Vectors")
                    st.write("Average weights that make each alternative the best")
                    fig_weights = px.bar(
                        cwv_df,
                        x=cwv_df.index,
                        y=cwv_df.columns,
                        title="Central Weight Vectors",
                        labels={"x": "Alternative", "y": "Weight", "variable": "Criterion"}
                    )
                    st.plotly_chart(fig_weights, use_container_width=True)
                    st.dataframe(cwv_df)
                
                # Display a summary table of rankings
                st.subheader("Ranking Summary Table")
                
                # Get the maximum number of alternatives across selected methods
                max_alternatives = max(len(ranking_df) for ranking_df in filtered_rankings.values())
                
                # Create a dictionary with padded lists to ensure equal length
                summary_data = {}
                for method, ranking_df in filtered_rankings.items():
                    alternatives = ranking_df['Alternative'].tolist()
                    if len(alternatives) < max_alternatives:
                        alternatives.extend([''] * (max_alternatives - len(alternatives)))
                    summary_data[method] = alternatives
                
                # Create DataFrame with the padded data
                summary_df = pd.DataFrame(summary_data)
                summary_df.insert(0, 'Rank', range(1, max_alternatives + 1))
                
                # Display the summary table
                st.dataframe(summary_df)
            else:
                st.warning("Please select at least one method to compare.")
        else:
            st.info("Please input your data using either manual input or by uploading an Excel file to see the comparison.")

    else:
        st.subheader("About")
        st.write("MEGA-MCDA is a comprehensive calculator that implements multiple Multicriteria Decision Analysis (MCDA) methods:")
        st.write("1. PSI Method: https://www.sciencedirect.com/science/article/abs/pii/S0261306909006396?via%3Dihub")
        st.write("2. MPSI-MARA: https://www.mdpi.com/2079-8954/10/6/248")
        st.write("3. MPSI-ARLON: https://doi.org/10.1016/j.seps.2024.101822")
        st.write("4. LOPCOW-DOBI: https://linkinghub.elsevier.com/retrieve/pii/S0305048322000974")
        st.write("5. SWARA-MOORA-3NAG: https://github.com/mcda-software/SWARA-MOORA-3NAG")
        st.write("6. CRITIC-MOORA-3N: https://github.com/lorransr/critic-moora-3n-method")
        st.write("7. CRITIC-GRA-3N: https://github.com/mcda-software/CRITIC-GRA-3N")
        st.write("8. MPSI-WASPAS: https://github.com/mcda-software/MPSI-WASPAS")
        st.write("To cite this work:")
        st.write("Araujo, Tullio Mozart Pires de Castro; Gomes, Carlos Francisco Simões.; Santos, Marcos dos. MEGA-MCDA (v1), Universidade Federal Fluminense, Niterói, Rio de Janeiro, 2024.")
    
    # Add logo to the sidebar
    logo_path = "https://i.imgur.com/g7fITf4.png"  # Replace with the actual path to your logo image file
    st.sidebar.image(logo_path, use_container_width=True)


if __name__ == "__main__":
    main()
