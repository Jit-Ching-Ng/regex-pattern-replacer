import { useRef, useState } from "react";

import { uploadDataset } from "../api/client.js";
import { formatBytes } from "../lib/format.js";
import { sampleFile } from "../lib/sampleData.js";
import { BrandMark } from "./Toolbar.jsx";

const ACCEPTED = [".csv", ".tsv", ".txt", ".xlsx", ".xls"];
const MAX_MB = 50;

function validate(file) {
  const extension = file.name.slice(file.name.lastIndexOf(".")).toLowerCase();
  if (!ACCEPTED.includes(extension)) return "Choose a .csv, .xlsx or .xls file.";
  if (file.size === 0) return "That file is empty.";
  if (file.size > MAX_MB * 1024 * 1024) return `Files can be up to ${MAX_MB} MB; this one is ${formatBytes(file.size)}.`;
  return null;
}

export default function UploadScreen({ onUploaded, onError }) {
  const inputRef = useRef(null);
  const [dragging, setDragging] = useState(false);
  const [progress, setProgress] = useState(null);
  const [fileName, setFileName] = useState("");

  const upload = async (file) => {
    const problem = validate(file);
    if (problem) {
      onError(problem);
      return;
    }
    setFileName(file.name);
    setProgress(0);
    try {
      const body = await uploadDataset(file, setProgress);
      onUploaded(body.dataset);
    } catch (error) {
      onError(error.message);
      setProgress(null);
    }
  };

  const onDrop = (event) => {
    event.preventDefault();
    setDragging(false);
    const file = event.dataTransfer.files?.[0];
    if (file) upload(file);
  };

  const uploading = progress !== null;

  return (
    <main className="intro">
      <header className="intro__head">
        <BrandMark />
        <span className="intro__product">Pattern Replace</span>
      </header>

      <h1 className="intro__title">Describe the pattern. We’ll write the regex and replace it across your sheet.</h1>
      <p className="intro__lede">
        Upload a CSV or Excel file, say what you’re looking for in plain English, such as “email addresses” or
        “phone numbers in any format”, and choose what to replace it with.
      </p>

      <div
        className={`dropzone${dragging ? " is-dragging" : ""}${uploading ? " is-busy" : ""}`}
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
      >
        {uploading ? (
          <div className="dropzone__progress" role="status">
            <p>
              {progress < 1 ? "Uploading" : "Reading"} <strong>{fileName}</strong>
            </p>
            <div className="meter" aria-hidden="true">
              <div className="meter__fill" style={{ transform: `scaleX(${Math.max(progress, 0.04)})` }} />
            </div>
          </div>
        ) : (
          <>
            <p className="dropzone__title">Drop a file here</p>
            <p className="dropzone__hint">CSV, XLSX or XLS, up to {MAX_MB} MB. The first sheet of a workbook is used.</p>
            <div className="dropzone__actions">
              <button type="button" className="button button--primary" onClick={() => inputRef.current?.click()}>
                Choose file
              </button>
              <button type="button" className="button button--quiet" onClick={() => upload(sampleFile())}>
                Try the sample contacts file
              </button>
            </div>
          </>
        )}
        <input
          ref={inputRef}
          type="file"
          accept={ACCEPTED.join(",")}
          className="visually-hidden"
          tabIndex={-1}
          onChange={(event) => {
            const file = event.target.files?.[0];
            event.target.value = "";
            if (file) upload(file);
          }}
        />
      </div>
    </main>
  );
}
