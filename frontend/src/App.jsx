import { useCallback, useState } from "react";

import { api } from "./api/client.js";
import DataTable from "./components/DataTable.jsx";
import FindReplacePanel from "./components/FindReplacePanel.jsx";
import HistoryList from "./components/HistoryList.jsx";
import Notice from "./components/Notice.jsx";
import Toolbar from "./components/Toolbar.jsx";
import TransformPanel from "./components/TransformPanel.jsx";
import UploadScreen from "./components/UploadScreen.jsx";
import { useDataset } from "./hooks/useDataset.js";

const TOOLS = [
  { id: "replace", label: "Find & replace" },
  { id: "transform", label: "AI transforms" },
];

export default function App() {
  const data = useDataset();
  const [tool, setTool] = useState("replace");
  const [notice, setNotice] = useState(null);
  const [historyBusy, setHistoryBusy] = useState(false);

  const notify = useCallback((kind, message) => setNotice({ kind, message, id: Date.now() }), []);
  const dismissNotice = useCallback(() => setNotice(null), []);

  const runHistoryAction = async (action, successMessage) => {
    setHistoryBusy(true);
    try {
      const body = await action(data.dataset.id);
      data.update(body.dataset, { showChanges: false });
      notify("success", successMessage(body));
    } catch (error) {
      notify("error", error.message);
    } finally {
      setHistoryBusy(false);
    }
  };

  if (data.restoring) {
    return <div className="boot" role="status">Opening your file…</div>;
  }

  if (!data.dataset) {
    return (
      <>
        <UploadScreen onUploaded={data.open} onError={(message) => notify("error", message)} />
        <Notice notice={notice} onDismiss={dismissNotice} />
      </>
    );
  }

  const { dataset } = data;

  return (
    <div className="workbench">
      <Toolbar dataset={dataset} onClose={data.close} />

      <aside className="rail" aria-label="Tools">
        <div className="tool-switch" role="tablist" aria-label="Tool">
          {TOOLS.map((item) => (
            <button
              key={item.id}
              type="button"
              role="tab"
              id={`tab-${item.id}`}
              aria-selected={tool === item.id}
              aria-controls={`panel-${item.id}`}
              className="tool-switch__tab"
              onClick={() => setTool(item.id)}
            >
              {item.label}
            </button>
          ))}
        </div>

        <section id={`panel-${tool}`} role="tabpanel" aria-labelledby={`tab-${tool}`} className="rail__panel">
          {tool === "replace" ? (
            <FindReplacePanel
              key={dataset.id}
              dataset={dataset}
              onApplied={(next, message) => {
                data.update(next);
                notify("success", message);
              }}
            />
          ) : (
            <TransformPanel
              key={dataset.id}
              dataset={dataset}
              onApplied={(next, message) => {
                data.update(next);
                notify("success", message);
              }}
            />
          )}
        </section>

        <HistoryList
          operations={dataset.operations}
          busy={historyBusy}
          onUndo={() => runHistoryAction(api.undo, () => "Undid the last change.")}
          onReset={() =>
            runHistoryAction(api.reset, (body) =>
              body.removed_operations ? "Restored the original file." : "The file is already in its original state.",
            )
          }
        />
      </aside>

      <main className="sheet" aria-label="Data">
        <DataTable
          table={data.table}
          loading={data.tableLoading}
          error={data.tableError}
          page={data.page}
          pageSize={data.pageSize}
          highlight={data.highlight}
          canHighlight={dataset.operations.length > 0}
          onPageChange={data.setPage}
          onPageSizeChange={data.setPageSize}
          onHighlightChange={data.setHighlight}
        />
      </main>

      <Notice notice={notice} onDismiss={dismissNotice} />
    </div>
  );
}
