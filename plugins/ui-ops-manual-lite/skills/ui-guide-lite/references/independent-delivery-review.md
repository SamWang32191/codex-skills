# 獨立交付審核（輕量版）

在組檔後、正式交付前閱讀本規格。它把文件內容、圖片隱碼、操作語意、版面結構與證據新鮮度交給另一個 reviewer 核對；本版沒有 DOCX renderer，因此不要求也不宣稱逐頁渲染通過。

## Reviewer 與交付狀態

沿用既有獨立審核機制，由另一位未參與產製的 reviewer 完成，不是 builder 改名、換一個 JSON id 或由腳本填欄位。工具與機械報告可整理 evidence，不能取代 reviewer 判讀。若本任務指定人工 reviewer，人工確認前保持 pending。`builder.id` 與 `reviewer.id` 必須明確且不同；腳本只能檢查欄位、檔案與狀態值，不能替使用者驗證真實身分。

沒有 reviewer、reviewer 不能讀取圖片、需求證據或相關檔案，或任何必要證據缺失／過期時，狀態為 `blocked`。繼續完成不依賴 reviewer 的已授權工作；目前產物只能標為 draft，不得宣稱通過。輕量版不因缺少 renderer 自動 blocked：只要其餘適用檢查已完成，仍可正式交付。

## 操作文字與計算內容

正文面向一般系統操作者。reviewer 要確認正文先用畫面名稱與日常用語交代操作、條件、選項與計算影響；必要業務詞在首次出現時簡短解釋，UI 原文照保留。代理試作操作、未儲存／未執行狀態、工具、hash、人工 pending 與 QA 限制應留在 QA record、finding ledger、review artifact 或交付說明。`draft` 以檔名或交付說明標示；只有有證據且對讀者有用的提醒才可放在既有正文章節。把「本次不要儲存」等試作限制寫成業務規則，或把 QA-only 細節當成讀者必須遵守的操作條件，屬內容錯誤。

可驗證的來源版本依既有版型在正文簡述一次即可；來源分類、程式識別字、方法追蹤、capture state 與雜湊放 QA。算例先用白話說明順序，只有必要時才用簡單數字例子，列明假設、公式或計算方式、順序與結果，並明確標示「合成示例，非實測」；避免大量公式符號、英文變數與程式術語，不可因此遺失條件或改變公式，也不可把合成結果當成實測或加入來源未支持的業務規則／結果。

reviewer 也要回查抽象措辭：保留「完整／正確／符合規範」時，正文需有具體欄位與判斷或精準引用；「具備權限者」需有具體角色證據；「依情況／相關設定」需列出情況與對應處理。這些不是禁用詞或字數限制；只有含糊到讀者無法操作、判斷或回查時才形成阻擋。

每個計算選項都要讓讀者找到適用條件、改變什麼、計算順序及未命中／未填退回規則。計算順序先用白話說明，正文使用 UI／業務名稱，不以內部變數或方法名稱代替；來源未證實時應標為待確認，不為具體而補造事實。

## Review artifact

review JSON 至少包含下列欄位（完整可接受值以 `scripts/audit_delivery.py` 現行 schema 為準）：

```json
{
  "schema_version": 1,
  "artifact": {"sha256": "<final-docx-sha256>"},
  "builder": {"id": "builder:..."},
  "reviewer": {"id": "reviewer:..."},
  "reviewed_files": [
    {"kind": "image", "path": "annotated/step1.png", "sha256": "<sha256>"},
    {"kind": "support", "role": "build_manifest", "path": "manual.json", "sha256": "<sha256>"},
    {"kind": "support", "role": "requirements", "path": "requirements.json", "sha256": "<sha256>"},
    {"kind": "support", "role": "screenshot_manifest", "path": "qa/create-task.json", "sha256": "<sha256>"},
    {"kind": "support", "role": "redaction_provenance", "path": "qa/create-task-provenance.json", "sha256": "<sha256>"},
    {"kind": "support", "role": "annotation_provenance", "path": "qa/create-task-annotation.json", "sha256": "<sha256>"},
    {"kind": "support", "role": "screenshot_manifest_validation", "path": "qa/create-task-manifest-validation.json", "sha256": "<sha256>"}
  ],
  "imageEvidence": [
    {
      "image": "annotated/step1.png",
      "redactionManifest": "qa/create-task.json",
      "annotationManifest": "qa/create-task.json",
      "provenance": "qa/create-task-provenance.json",
      "annotationProvenance": "qa/create-task-annotation.json"
    }
  ],
  "checks": {
    "requirements": {"status": "pass", "reason": "...", "evidence": ["requirements.json"]},
    "redaction": {"status": "pass", "reason": "...", "evidence": ["annotated/step1.png", "qa/create-task.json"]},
    "operation": {"status": "pass", "reason": "...", "evidence": ["annotated/step1.png", "manual.json"]},
    "layout_structure": {"status": "pass", "reason": "...", "evidence": ["manual.json"]}
  },
  "render_visual": {"status": "out_of_scope", "reason": "輕量版沒有 DOCX renderer。"},
  "overall": "pass"
}
```

`reviewed_files` 的路徑相對於 review JSON 所在資料夾，且每筆都必須是實際存在的檔案並與 SHA-256 相符。支援檔案要以語義 role 或腳本現行支援的頂層 evidence 引用標示用途，不要靠檔名子字串猜測需求或 manifest。至少綁定：

- 最終 DOCX 的 `artifact.sha256`。
- DOCX 所有嵌入圖片的 hash；raw／未遮蔽圖片不可列為交付圖片。
- 最終 build manifest 與需求／需求 snapshot。
- 會影響圖片或操作內容的整合 screenshot manifest、redaction provenance、validator 報告及其他相關證據；不要另外維護一套互相矛盾的 redaction／annotation schema。
- 每張 annotated 圖的工具生成 annotation provenance；它必須同時出現在該圖片的 `imageEvidence.annotationProvenance` 和 `reviewed_files`，並以實際 hash 綁定。

只要正式 audit 傳入 `--manifest`，就會要求 review JSON 的 `imageEvidence` 逐張列出每個嵌入圖片，並以 `redactionManifest`、`annotationManifest`（同一份整合 screenshot manifest）、`provenance` 和 `annotationProvenance` 回指 `reviewed_files` 中已核對 hash 的 support 檔；audit 會再解析該 screenshot manifest 的實際 provenance refs、父圖／輸出路徑和 hash，不能用任意同名或不相干 support 檔代替。不因章節／步驟是否宣告 evidence 而省略。缺少任一圖片鏈、support 檔或 hash 綁定時，`--manifest` + `--review` 的正式 audit 必須維持 `blocked`；structure-only 報告不能取代這個 gate。

四類 checks 固定為 `requirements`、`redaction`、`operation`、`layout_structure`。每一類要有 `status`、非空 `reason` 與只引用 `reviewed_files[].path` 的 `evidence`。`requirements` 與 `layout_structure` 不可填 `na`；`redaction` 或 `operation` 只有在本任務明確不含相應內容時才可填 `na`，並說明理由。圖片已嵌入時，`redaction` 與 `operation` 的 pass 必須有圖片 evidence。任何缺證據、無法核對或語意尚未完成都填 `blocked`，發現錯誤填 `fail`。

`render_visual.status` 只能填 `not_performed` 或 `out_of_scope`（另依腳本規格使用 `blocked`／`fail`），並提供原因；**不能填 `pass`**。`overall: "pass"` 只在另一位未參與產製的 reviewer 確實完成、四類適用 checks 通過、artifact／所有 reviewed files hash 相符且 render_visual 仍明確在輕量版範圍外時使用。

## 文字與計算回歸案例

下列情境直接判為相應 check 的 `fail` 或 `blocked`，並沿用既有 finding ledger：

| 情境 | 判定 |
| --- | --- |
| 正文把代理試作、未儲存／未執行、工具、hash、人工 pending 或 QA 限制寫成業務操作條件／結果，或把「本次不要儲存」當成業務規則 | `requirements` 或 `operation` 為 `fail`；若只缺少可操作的證據則為 `blocked`。draft 應在檔名／交付說明標示，必要提醒需有證據且對讀者有用。 |
| 保留「完整／正確／符合規範」卻沒有具體欄位與判斷或精準引用；以「具備權限者」限制操作卻沒有具體角色證據；以「依情況／相關設定」卻沒有情況對應處理 | 含糊導致讀者無法操作、判斷或回查時，`requirements` 或 `operation` 為 `fail`；純冗詞或偏好且不影響操作可記為 accepted limitation。 |
| 計算選項缺少適用條件、改變什麼、計算順序或未命中／未填退回規則，或以內部變數／方法名稱代替 UI／業務名稱 | `operation` 為 `fail`；來源不足以判定必要資訊時為 `blocked`，不可自行補造。 |
| 算例未說明必要假設／公式／順序，未標示「合成示例，非實測」，或把合成數值宣稱為實測／來源未支持的業務規則／結果 | `operation` 或 `requirements` 為 `fail`；移除算例或補齊有證據的假設與標示。 |

## 執行順序

先產生機械結構報告；此命令只作前置檢查，不能作為正式交付完成條件：

```text
Windows PowerShell:
& "<venv>\Scripts\python.exe" "<skill>\scripts\audit_delivery.py" --docx "<final.docx>" --output "<qa>/structure.json" --image-evidence "<qa>/delivered-images.json" --require-default-layout
macOS/Linux:
"<venv>/bin/python" "<skill>/scripts/audit_delivery.py" --docx "<final.docx>" --output "<qa>/structure.json" --image-evidence "<qa>/delivered-images.json" --require-default-layout
```

reviewer 讀取需求、最終 DOCX、所有嵌入圖片、redacted／annotated 圖片與支持檔案，完成上面的 review JSON（每張嵌入圖都要有 `imageEvidence`，並回指同一份整合 screenshot manifest、provenance 和已核對的 support files）。再用不同輸出檔驗證其綁定；這個帶 `--review` 與 `--manifest` 的命令才是正式交付 gate：

```text
Windows PowerShell:
& "<venv>\Scripts\python.exe" "<skill>\scripts\audit_delivery.py" --docx "<final.docx>" --review "<qa>/review.json" --manifest "<workspace>/manual.json" --output "<qa>/review-validation.json" --image-evidence "<qa>/delivered-images.json" --require-acceptance --acceptance-catalog "<skill>\references\acceptance-rule-catalog.json" --require-default-layout
macOS/Linux:
"<venv>/bin/python" "<skill>/scripts/audit_delivery.py" --docx "<final.docx>" --review "<qa>/review.json" --manifest "<workspace>/manual.json" --output "<qa>/review-validation.json" --image-evidence "<qa>/delivered-images.json" --require-acceptance --acceptance-catalog "<skill>/references/acceptance-rule-catalog.json" --require-default-layout
```

檢查 `mechanical_status` 與 `independent_review.status`，不能只看 exit code；exit code 0 代表報告已寫出，不代表 DOCX、圖片或 review 自動通過。若 audit 提示 `manual_review`，由 reviewer 依實際文件與使用者已明示的版型例外判讀；不要把它靜默當作 pass。

本技能的正式交付一律啟用 [acceptance-rule-catalog.json](acceptance-rule-catalog.json)；正式 audit 命令必須顯式加入 `--require-acceptance --acceptance-catalog "<skill>/references/acceptance-rule-catalog.json"`（任務若有明示範圍例外，改用保留原始 ID 的任務限定 catalog）。缺少 `acceptance`、catalog item、最終輸出 evidence 或 hash 時，正式 audit 必須維持 blocked。未帶 `--require-acceptance` 僅是舊版 CLI 的相容行為，不構成目前技能交付。Lite 的 acceptance 不增加 DOCX renderer；仍只讀回文字／表格／圖片與結構並檢視 screenshot PNG。

`delivered-images.json` 是同一 QA record 的 `assetLedger` freeze allowlist，格式為 `{"schema_version": 1, "assets": [{"path": "annotated/step.png", "sha256": "..."}]}`。`--image-evidence` 會比對 DOCX 實際嵌入的媒體 bytes，攔截舊圖、freeze 後改圖、raw 路徑與未列入 allowlist 的圖；`--require-default-layout` 只檢查更新紀錄表首列的 `版本`／`日期`／`更新內容`，不取代內容讀回或圖片語意審核。兩次 audit 必須使用同一 allowlist 與版面 flag。

macOS／Linux 使用同一 venv 根目錄的 `bin/python` 取代 `Scripts\python.exe`；這只改 Python launcher，不改 manifest、review schema 或檢查範圍。

## 四類核對內容

- `requirements`：需求範圍、目標畫面、版本依據（若有）與目前文件內容相符。抽象措辭有具體欄位／判斷或精準引用，未證實的角色權限、QA-only 限制與試作狀態沒有被寫成正文規則。
- `redaction`：實際檢視整合 manifest 指向的 redacted 圖與 raw／redacted 對照，身分 ID、地址、保單號、帳單號、合約號等不可辨識；金額依使用者要求處理，預設可見；controls／labels 仍可讀。確認 raw 僅在受限區，沒有進入 DOCX 或交付包。
- `operation`：紅框、編號、caption、控制項與狀態相符；操作流程、欄位限制、成功影響、失敗／取消與操作後檢核均有證據。每個計算選項的適用條件、影響、順序及未命中／未填退回規則可由正文與證據核對。Pillow、DOM 或 validator 結果只能作輔助，不能取代直接看圖或人工審閱。
- `layout_structure`：`verify_docx.py` 的章節、更新紀錄位置、清單重編、欄位表、圖片封裝與圖說關係，以及表格／圖片相對容器可用內容區置中、超寬高、固定列高、numbering 風險與嵌圖尺寸合理。這不是 DOCX 渲染結果。

阻擋項固定包括錯誤／誤導操作、主要流程或關鍵實圖缺失、敏感值漏遮、遮住控制項／labels 或使其無法辨識、內容不可讀。阻擋項未解時相應 check 為 `fail`／`blocked`，overall 不得為 `pass`。非阻擋的次要欄位深度、措辭精緻度和輕微美觀可保留可用成品，於 check 的 `reason`／`evidence` 記為 `accepted limitation`；不可用 accepted limitation 包裝上述 blocker。

每輪把同一份 finding ledger 的未解項目與新 findings 合併。若同一缺陷使用同一策略連續兩次無改善，停止無效策略而非必要驗證，改做定點最小修復、使用者已明示的範圍縮限或回報阻擋；不能只改狀態、換 reviewer 名稱或靠舊 artifact 取得 pass。

文件、嵌入圖片、build／整合 screenshot manifest、provenance／validator report 或需求證據任何一項改動，都使受影響的 review 失效：重算 artifact 與相關 reviewed files hash，重新完成受影響 checks。不能只替舊 review 換 hash，也不必為未受影響的內容無故全部重寫。

交接紀錄固定列出六項並逐項附證據與狀態：**隱碼、標註、結構、獨立審核、證據雜湊、交付範圍**。renderer、權限、reviewer 身分與 fallback 狀態留在對話或外部 QA 紀錄，不寫入 DOCX。

## 操作文字回查（測試規範）

依 [manual-writing-standard.md](manual-writing-standard.md) 核對最終 DOCX 與來源：正文是否以系統操作者為讀者，控制項名稱、前置條件、動作順序、否定、數值、結果與圖說是否一致；每個計算選項是否有適用條件、影響、順序及未命中／未填退回規則；不得以流暢文字補造限制、權限或下游影響。發現沿用現有 requirements／operation 的 reason／evidence 及 finding ledger，記錄原句／問題／修正或保留理由並綁定實際輸出 hash，不要求每句紀錄、不增加 schema 欄位或審核輪次。影響操作的錯誤、含糊到無法操作或證據缺口依既有 fail／blocked 規則處理；純措辭改善維持非阻擋分類。人工尚未回覆時保留 pending，builder 或腳本不代填人工通過。

## 原子 acceptance 與最終輸出證據

本技能的每次正式交付都以 [acceptance-rule-catalog.json](acceptance-rule-catalog.json) 為唯一規範目錄。既有四類 `requirements`、`redaction`、`operation`、`layout_structure` 仍是摘要與總結 gate；catalog 的原子項目是它們的可追溯明細，不另建立逐句清單。review artifact 另加：

```json
{
  "acceptance": {
    "schema_version": 1,
    "items": [
      {
        "id": "annotation-color",
        "applicable": true,
        "status": "pass",
        "reason": "最終 annotated PNG 的每個紅框與 badge 均已直接檢視；target_scope=全部標註，location=qa/annotated，rationale=標註色與文件 teal 分離。",
        "evidence": ["qa/review.json", "qa/annotated/step-01.png"],
        "actual_artifacts": [
          {"path": "qa/annotated/step-01.png", "sha256": "<sha256>", "scope": "final annotated image"}
        ]
      }
    ]
  }
}
```

每個 catalog row（`required: true`）在 `acceptance.items` 恰好出現一次；`applicability: "always"` 的 row 必須維持 `applicable: true`，`applicability: "conditional"` 的 row 只有在明示的 scope 例外成立時才可 `applicable: false`，並以 `na`／`not_applicable` 和 reason 說明。每個 `applicable` 項目要有 outcome `status`、target scope、location、evidence 與 rationale（由支援欄位或 `reason` 明示），evidence 必須是 `reviewed_files[].path` 的精確值，`pass` 必須綁定實際最終輸出檔與 SHA-256。可將同一組 evidence 套用到多個 item，或在一項中涵蓋多張圖／多個流程，但必須先列出 exhaustive target set；不能用 source-only 規範、builder 宣稱或機械 exit code 代替最終輸出證據。非適用項目要有 reason；缺項、重複、無法讀取、`pending`／`blocked`／`fail` 或 hash 不符均不得為 pass。

builder 可以先完成產製與機械／結構／來源自查並把文件交為 `draft`；這不等於獨立交付審核。獨立 reviewer 必須直接讀取真正最終 DOCX、所有嵌入圖片、可直接檢視的 screenshot PNG 與相關證據，不能由 builder 改名、換 id 或由腳本代填 reviewer pass。四模型八份文件的 plugin 回歸執行本身也不是各份 DOCX 的獨立 reviewer；人工審閱未完成時保留 `independent review pending`。

本版的 `lite-readback-render-scope` 是適用的原子項目：只能做最終 DOCX 文字／表格／圖片讀回、結構檢查及 screenshot PNG 直接檢視；不得渲染 DOCX，`render_visual.status` 必須誠實填 `not_performed` 或 `out_of_scope`（缺必要證據仍為 `blocked`）。
