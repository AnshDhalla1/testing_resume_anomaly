import streamlit as st
import os
import json
import requests
import tempfile
import pandas as pd
import time
import openai
from main_final import process_resume
from utils.retrieve_doc import get_all_documents
from utils.export_excel import export_to_excel

API_KEY = os.getenv("GDRIVE_API_KEY")
DRIVE_API_URL = "https://www.googleapis.com/drive/v3/files"

# ----- Google Drive API Helper Functions -----
def list_drive_files(folder_id):
    """
    List all public files in a specific Google Drive folder using an API key.
    Returns a list of files with name, id, and modifiedTime.
    """
    files = []
    page_token = None
    
    while True:
        params = {
            'q': f"'{folder_id}' in parents and trashed=false",
            'fields': 'nextPageToken,files(id,name,modifiedTime)',
            'key': API_KEY,
            'orderBy': 'modifiedTime desc',
            'pageToken': page_token if page_token else ''
        }
        response = requests.get(DRIVE_API_URL, params=params)
        response.raise_for_status()  
        
        data = response.json()
        for file in data.get('files', []):
            files.append({
                'name': file['name'],
                'id': file['id'],
                'modifiedTime': file.get('modifiedTime', 'N/A')
            })
        
        page_token = data.get('nextPageToken')
        if not page_token:
            break
    
    return files

def download_drive_file(file_id, file_name):
    """
    Download a file from Google Drive to a temporary location using an API key.
    Returns the path to the temporary file.
    """
    download_url = f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media&key={API_KEY}"
    response = requests.get(download_url, stream=True)
    response.raise_for_status()
    
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file_name)[1])
    for chunk in response.iter_content(chunk_size=8192):
        if chunk:
            temp_file.write(chunk)
    temp_file.close()
    
    return temp_file.name
# ----- End Google Drive Helpers -----

def convert_to_dataframe(parsed_json):
    if isinstance(parsed_json, list):
        return pd.DataFrame(parsed_json)
    elif isinstance(parsed_json, dict):
        return pd.json_normalize(parsed_json)
    else:
        return pd.DataFrame([parsed_json])

def process_with_retry(temp_file_path, file_name, max_retries=2):
    retries = 0
    while retries < max_retries:
        try:
            result_dict = process_resume(temp_file_path, file_name)
            return result_dict
        except openai.LengthFinishReasonError as e:
            retries += 1
            st.warning(f"Error processing {file_name}, retrying {retries}/{max_retries}.")
            if retries < max_retries:
                time.sleep(5)
            else:
                st.error(f"Failed to process {file_name} after {max_retries} retries.")
                return None

def display_llm_output(parsed_json, time_stats, inserted_id, unique_id):
    st.subheader("個人情報")
    st.dataframe(convert_to_dataframe(parsed_json.get('個人的', {})))
    st.subheader("希望条件")
    st.dataframe(convert_to_dataframe(parsed_json.get('望ましい', {})))
    st.subheader("資格")
    qualifications = convert_to_dataframe(parsed_json.get('資格_', []))
    if '年' in qualifications.columns:
        qualifications['年'] = qualifications['年'].astype(str).str.replace(',', '')
    if '月' in qualifications.columns:
        qualifications['月'] = qualifications['月'].astype(str).str.replace(',', '')
    st.dataframe(qualifications)
    st.subheader("スキルサマリー")
    skills_summary = parsed_json.get('スキルサマリー', {})
    self_pr = skills_summary.get('自己PR', '')
    st.text_area("自己PR", self_pr if isinstance(self_pr, str) else "", height=200)
    st.subheader("職歴")
    st.dataframe(convert_to_dataframe(parsed_json.get('職歴', [])))
    st.subheader("スキル評価")
    skill_eval = parsed_json.get('スキル評価', {})
    for category, skills in skill_eval.items():
        st.markdown(f"**カテゴリ:** {category}")
        st.dataframe(pd.DataFrame.from_dict(skills, orient='index'))
    st.subheader("時間統計")
    st.json(time_stats)
    st.write(f"**MongoDBに保存されたID:** `{inserted_id}`")
    st.write(f"**Unique ID:** `{unique_id}`")

def run_app():
    st.title("Resume Parser Application (GiveryAI)")
    
    tab1, tab2, tab3 = st.tabs(["アップロード", "保存済み結果", "Google Drive Files"])
    
    # --- Tab 1: Manual Upload ---
    with tab1:
        uploaded_files = st.file_uploader(
            "Please upload the resume files",
            type=["pdf", "doc", "docx", "xlsx"],
            accept_multiple_files=True
        )

        if uploaded_files:
            for uploaded_file in uploaded_files:
                with st.expander(f"### 処理中: **{uploaded_file.name}**"):
                    # Check if the file has been processed already
                    if uploaded_file.name not in st.session_state:
                        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(uploaded_file.name)[1]) as tmp:
                            tmp.write(uploaded_file.getbuffer())
                            temp_file_path = tmp.name

                        with st.spinner(f"{uploaded_file.name} の処理中..."):
                            result_dict = process_with_retry(temp_file_path, uploaded_file.name)

                        if result_dict is None:
                            st.error(f"Could not process {uploaded_file.name} after multiple retries.")
                            continue  # Skip to the next file

                        # Store the results in session state to avoid re-running the pipeline
                        st.session_state[uploaded_file.name] = {
                            "result_dict": result_dict,
                            "temp_file_path": temp_file_path,
                            "uploaded_file_name": uploaded_file.name
                        }

                    # Fetch stored results
                    result_dict = st.session_state[uploaded_file.name]["result_dict"]
                    llm_output = result_dict["llm_output"]
                    time_stats = result_dict["time_stats"]
                    unique_id = result_dict["unique_id"]
                    inserted_id = result_dict["inserted_id"]

                    st.subheader(f"### LLM 出力: **{uploaded_file.name}**")
                    try:
                        loaded_json = json.loads(llm_output)
                        if "parsed" in loaded_json:
                            parsed_json = loaded_json["parsed"]
                            display_llm_output(parsed_json, time_stats, inserted_id, unique_id)
                            st.markdown("---")

                            if st.button(f"Export to Excel: {uploaded_file.name}"):
                                output_file = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx").name
                                
                                excel_file = export_to_excel(parsed_json, output_file)
                                
                                st.download_button(
                                    label="Download Excel",
                                    data=open(excel_file, "rb").read(),
                                    file_name=f"{uploaded_file.name}.xlsx",
                                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                                )
                        else:
                            st.error("期待される 'parsed' キーがLLM出力に見つかりませんでした。")
                    except json.JSONDecodeError:
                        st.error("JSONの解析に失敗しました。下記に生データを表示します:")
                        st.text_area("LLM 出力 (生データ)", llm_output, height=300)


    # --- Tab 2: Saved Results ---
    with tab2:
        st.header("保存済み結果の一覧")

        documents = get_all_documents()

        if documents:

            documents.sort(key=lambda x: x.get("timestamp", 0), reverse=True)

            for doc in documents:
                _id = str(doc.get("_id"))
                unique_id = doc.get("unique_id", "N/A")
                file_name = doc.get("file_name", "N/A")
                timestamp = doc.get("timestamp", "N/A")
                total_time = doc.get("time_stats", {}).get("total_time", "N/A")

                with st.expander(f"View {file_name} | Doc ID: {_id}"):
                    st.markdown(f"""
                    <div style="border: 2px solid #ddd; border-radius: 5px; padding: 10px; margin-bottom: 10px;">
                        <p><strong>Unique ID:</strong> {unique_id}</p>
                        <p><strong>Timestamp:</strong> {timestamp}</p>
                        <p><strong>Parse Time:</strong> {total_time} seconds</p>
                    </div>
                    """, unsafe_allow_html=True)

                    if st.button(f"View Parsed Data for Unique ID: {unique_id}"):
                        st.subheader(f"パース結果: {_id}")
                        stored_llm_output = doc.get("llm_output", {})
                        time_stats = doc.get("time_stats", {})
                        display_llm_output(stored_llm_output, time_stats, _id, unique_id)
                        st.markdown("---")

        else:
            st.write("保存済みの結果がありません。")


    # --- Tab 3: Google Drive Resumes ---
    with tab3:
        st.header("Google Drive Resumes")
        folder_id = st.text_input("Google Drive Folder ID", "1hCurZKwbn8OXm3fdD4n0I376kB3iPNsx")
        
        if folder_id:
            try:
                drive_files = list_drive_files(folder_id)
                if drive_files:
                    drive_df = pd.DataFrame(drive_files)
                    drive_df.rename(columns={
                        "name": "File Name", 
                        "id": "File ID", 
                        "modifiedTime": "Modified Time"
                    }, inplace=True)
                    st.dataframe(drive_df)
                    
                    options = [f"{f['name']} (ID: {f['id']})" for f in drive_files]
                    selected_files = st.multiselect("Select files to process", options)

                    if selected_files:
                        if st.button("Process Selected Files"):
                            for sel in selected_files:
                                # Split on " (ID: " to separate file name and ID
                                file_name = sel.split(" (ID: ")[0]
                                file_id = sel.split(" (ID: ")[1].rstrip(")")  # Remove the closing parenthesis
                                with st.expander(f"### 処理中: **{file_name}**"):    
                                    with st.spinner(f"Downloading {file_name} from Google Drive..."):
                                        temp_file_path = download_drive_file(file_id, file_name)
                                    
                                    with st.spinner(f"{file_name} の処理中..."):
                                        result_dict = process_with_retry(temp_file_path, file_name)
                                    
                                    if result_dict:
                                        llm_output = result_dict["llm_output"]
                                        time_stats = result_dict["time_stats"]
                                        unique_id = result_dict["unique_id"]
                                        inserted_id = result_dict["inserted_id"]
                                        
                                        st.subheader(f"### LLM 出力: **{file_name}**")
                                        try:
                                            loaded_json = json.loads(llm_output)
                                            if "parsed" in loaded_json:
                                                parsed_json = loaded_json["parsed"]
                                                display_llm_output(parsed_json, time_stats, inserted_id, unique_id)
                                                st.markdown("---")
                                            else:
                                                st.error("期待される 'parsed' キーがLLM出力に見つかりませんでした。")
                                        except json.JSONDecodeError:
                                            st.error("JSONの解析に失敗しました。下記に生データを表示します:")
                                            st.text_area("LLM 出力 (生データ)", llm_output, height=300)
                                    else:
                                        st.error(f"Could not process {file_name} after multiple retries.")
                                    # Clean up temp file
                                    if os.path.exists(temp_file_path):
                                        os.remove(temp_file_path)
                else:
                    st.write("No files found in the specified folder. Ensure the folder is publicly accessible.")
            except requests.exceptions.HTTPError as e:
                st.error(f"Error accessing Google Drive: {e}")
                st.write("Ensure the folder is publicly accessible and the API key is correct.")

if __name__ == "__main__":
    run_app()