# 離線中文錄音轉文字工具

把中文錄音檔轉成繁體中文文字（台灣用語），**轉錄過程完全離線**，錄音內容不會離開電腦。內建可自訂的字典：

- **詞彙表（同音字修正）**：登錄正確的詞（例如人名「王小明」），轉錄結果中同音的字（汪曉明）會自動改成登錄的寫法。支援破音字，可逐條開啟模糊音（zh/z、ch/c、sh/s、l/n、in/ing、en/eng）。
- **取代規則**：「原文字 → 替換為」的強制取代，轉錄完成後最後套用。
- **辨識提示**：詞彙表的詞會餵給辨識模型當提示，讓模型一開始就傾向輸出這些詞。

## Windows 打包步驟（只需做一次，需要網路）

1. 安裝 [Python 3.12](https://www.python.org/downloads/)（安裝時勾選 **Add python.exe to PATH**）
2. 把整個專案資料夾複製到 Windows 電腦
3. 雙擊執行 `scripts\build_windows.bat`
   - 自動建立環境、安裝套件、下載模型（約 1.5GB）、打包
4. 完成後，`dist\OfflineTranscriber\` 整個資料夾就是可攜式程式
   - 複製到任何 Windows 電腦（含離線電腦）皆可使用
   - 執行其中的 `OfflineTranscriber.exe`

> 若目標電腦開啟 exe 時出現 DLL 錯誤，請安裝
> [Microsoft Visual C++ Redistributable](https://aka.ms/vs/17/release/vc_redist.x64.exe)（多數電腦已內建）。

## 使用方式

1. 開啟 `OfflineTranscriber.exe`
2. 「轉錄」分頁：選擇音訊檔（支援 m4a / mp3 / wav / mp4 等常見格式）→ 開始轉錄
   - 第一次轉錄需載入模型，約需 10–30 秒
   - 轉錄速度約為錄音長度的 1/3 ～ 1 倍（依電腦效能而定）
3. 完成後可儲存為 `.txt`（純文字）或 `.srt`（含時間戳字幕）

## 字典編輯

- 在程式的「字典」分頁直接新增 / 編輯 / 刪除
- 也可以直接用記事本編輯程式旁邊的 `dictionary.json`：

```json
{
  "words": [
    {"word": "王小明", "enabled": true, "use_prompt": true, "fuzzy": false}
  ],
  "replacements": [
    {"from": "錯誤寫法", "to": "正確寫法", "enabled": true}
  ]
}
```

| 欄位 | 說明 |
|---|---|
| `word` | 正確的詞（至少兩個字） |
| `enabled` | 是否啟用這條規則 |
| `use_prompt` | 是否加入辨識提示 |
| `fuzzy` | 是否啟用模糊音比對（容易誤代換，預設關閉） |

修改後重新按「開始轉錄」即生效（每次轉錄都會重新讀取字典）。

## 開發（macOS / Linux）

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt huggingface-hub pytest
.venv/bin/python scripts/download_model.py   # 一次性下載模型
.venv/bin/python src/main.py                 # 啟動 GUI
.venv/bin/python -m pytest tests/            # 單元測試
```

## Windows 驗收清單

在乾淨的（最好是離線的）Windows 電腦上：

- [ ] `OfflineTranscriber.exe` 可開啟（ctranslate2 DLL 正常載入）
- [ ] 可轉錄一個真實的 m4a/mp3 檔（PyAV 解碼正常）
- [ ] 輸出為繁體中文（OpenCC 正常）
- [ ] 字典分頁新增詞彙後，重新轉錄會套用（dictionary.json 正常讀寫）
- [ ] 拔網路線 / 關 Wi-Fi 重複以上步驟，全部正常

## 技術架構

- 語音辨識：[faster-whisper](https://github.com/SYSTRAN/faster-whisper)（Whisper large-v3-turbo、CPU int8 量化、`local_files_only=True` 保證離線）
- 簡轉繁：OpenCC s2twp（台灣用語）
- 同音字比對：pypinyin（破音字以讀音集合交集比對，長詞優先、不跨標點、不重疊）
- 後處理順序：OpenCC → 同音字修正 → 取代規則（最終覆寫）
- GUI：Tkinter（轉錄於背景執行緒，queue 回傳進度）
- 打包：PyInstaller onedir，模型資料夾置於 exe 旁
