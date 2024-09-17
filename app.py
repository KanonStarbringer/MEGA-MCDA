import streamlit as st
import pandas as pd
import numpy as np
import xlsxwriter
import openpyxl
from st_aggrid import AgGrid
import io
from scipy.integrate import quad
from reportlab.lib.pagesizes import letter, A4
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle
import plotly.express as px

# Set the app title and description
st.set_page_config(
    page_title="PSI and MPSI-MARA calculator",
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
        file_name="MEREC_SPOTIS_template.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

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

    # Convert all the criteria columns (except the 'A/C' column) to numeric values
    for col in df.columns[1:]:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    
    return df, criterion_types, df.shape[0], num_criteria

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

    return edited_matrix, criterion_types

def normalize_matrix(df, criterion_types):
    normalized_df = df.copy()
    for j, criterion_type in enumerate(criterion_types):
        if criterion_type == "Benefit":
            col_max = df.iloc[:, j+1].max()
            normalized_df.iloc[:, j+1] = df.iloc[:, j+1] / col_max
        else:
            col_min = df.iloc[:, j+1].min()
            normalized_df.iloc[:, j+1] = col_min / df.iloc[:, j+1]
    return normalized_df

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

def dobi_rank_alternatives(integrated_values):
    """
    Rank alternatives based on their integrated values using the DOBI method.
    
    Parameters:
    - integrated_values: A list of integrated values for each alternative
    
    Returns:
    - A DataFrame with alternatives and their rankings.
    """
    rankings_df = pd.DataFrame({
        'Alternative': ['A' + str(i+1) for i in range(len(integrated_values))],
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
    f_dhat_matrix = d_hat_matrix.copy()

    # Loop through each row (i.e., each alternative) to calculate f(d_hat)
    for i in range(d_hat_matrix.shape[0]):
        row_sum = d_hat_matrix.iloc[i, 1:].sum()  # Sum of all criteria for the alternative
        
        if row_sum == 0:
            row_sum = 1e-10  # Avoid division by zero

        # Divide each element in the row by the row sum
        f_dhat_matrix.iloc[i, 1:] = d_hat_matrix.iloc[i, 1:] / row_sum

    # Return the entire f(dhat) matrix
    return f_dhat_matrix

# Calculate Z_i^(1) for DOBI method

def Z_i_1_v2(normalized_matrix_dobi, f_dhat_matrix, weights, psi1, psi2, zeta):
    """
    Calculate \mathbb{Z}_{i}^{(1)\psi_1,\psi_2,\zeta} for DOBI method based on the normalized DOBI matrix and f(dhat) matrix.
    """
    num_alternatives = normalized_matrix_dobi.shape[0]
    num_criteria = normalized_matrix_dobi.shape[1] - 1  # Exclude 'A/C' column

    Z_L1_values = []

    # Loop through each alternative
    for i in range(num_alternatives):
        # Step 1: Numerator: Sum of the row (sum of the normalized values for alternative i)
        dhat_i = normalized_matrix_dobi.iloc[i, 1:]
        sum_dhat = np.sum(dhat_i)

        # Step 2: Calculate the complex denominator
        inner_sum = 0
        for j in range(num_alternatives):
            if j != i:  # Avoid self-reference
                f_dhat_ij = f_dhat_matrix.iloc[i, j+1]  # Extract the correct value from f(dhat)

                # Pairwise comparison between criteria based on weights
                term1 = 1 / (weights[i] * weights[j] * (psi1 + psi2))
                term2 = (psi1 * ((1 - f_dhat_ij) / f_dhat_ij)) ** zeta
                term3 = psi2 * (f_dhat_ij / (1 - f_dhat_ij)) ** zeta

                # Add up these terms for the inner sum
                inner_sum += term1 * (term2 + term3)

        # Step 3: Final denominator calculation
        denom = 1 + (1 / (weights[i] * (psi1 + psi2))) * inner_sum
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
    Z_L2_values = []

    for i in range(num_alternatives):
        # Numerator: Sum of the row (sum of the normalized values for alternative i)
        row_sum = np.sum(normalized_matrix_dobi.iloc[i, 1:])

        # Subtract the value of Z_L1 from the row sum for the current alternative
        Z_L1_value = Z_i_1_v2(normalized_matrix_dobi, f_dhat_matrix, weights, psi1, psi2, zeta)[i]
        adjusted_sum = row_sum - Z_L1_value

        # Initialize the denominator
        inner_sum = 0
        for j in range(num_alternatives):
            if j != i:  # Avoid self-reference
                f_dhat_ij = f_dhat_matrix.iloc[i, j+1]

                # Pairwise comparison logic for alternative i and criteria j
                term1 = 1 / (weights[i] * weights[j] * (psi1 + psi2))
                term2 = (psi1 * (1 - f_dhat_ij) / f_dhat_ij) ** zeta
                term3 = psi2 * (f_dhat_ij / (1 - f_dhat_ij)) ** zeta
                inner_sum += term1 * (term2 + term3)

        # Calculate final denominator for Z_L2
        denominator = 1 + (1 / (weights[i] * (psi1 + psi2))) * inner_sum
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

def main():
    menu = ["Home", "PSI", "MPSI-MARA", "MPSI-ARLON", "LOPCOW-DOBI", "About"]

    choice = st.sidebar.selectbox("Menu", menu)

    if choice == "Home":
        st.header("Home")
        st.subheader("Multicriteria Methods Calculator")
        st.write("This is a MCDA Calculator for the PSI, MPSI-MARA, MPSI-ARLON and LOPCOW-DOBI Methods.")
        st.write("To use this Calculator, define the number of alternatives and criteria you'll measure.")
        st.write("Then, define if the criteria are of benefit (more is better) or cost (less is better).")

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

    else:
        st.subheader("About")
        st.write("The PSI Method is a method created by Maniya et al. [2010]")
        st.write("The Hybrid MCDA Method MPSI-MARA is a method created by Gligoric et al. [2022]")
        st.write("Both Articles")
        st.write("https://www.sciencedirect.com/science/article/abs/pii/S0261306909006396?via%3Dihub")
        st.write('https://www.mdpi.com/2079-8954/10/6/248')
        st.write("To cite this work:")
        st.write("Araujo, Tullio Mozart Pires de Castro; Gomes, Carlos Francisco Simões.; Santos, Marcos dos. PSI and MPSI-MARA For Decision Making (v1), Universidade Federal Fluminense, Niterói, Rio de Janeiro, 2023.")
    
    # Add logo to the sidebar
    logo_path = "https://i.imgur.com/g7fITf4.png"  # Replace with the actual path to your logo image file
    st.sidebar.image(logo_path, use_column_width=True)


if __name__ == "__main__":
    main()