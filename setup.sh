mkdir -p ~/.streamlit/

echo "\
[general]\n\
email = \"tulliopiresl@gmail.com\"\n\
" > ~/.streamlit/credentials.toml

echo "\
[server]\n\
headless = true\n\
port = $PORT\n\
enableCORS = false\n\
\n\
" > ~/.streamlit/config.toml

pip install -r requirements.txt
streamlit run app.py
