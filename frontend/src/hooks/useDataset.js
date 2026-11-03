import { useCallback, useEffect, useState } from "react";

import { api } from "../api/client.js";

const URL_PARAM = "dataset";

function readDatasetIdFromUrl() {
  return new URLSearchParams(window.location.search).get(URL_PARAM);
}

function writeDatasetIdToUrl(id) {
  const url = new URL(window.location.href);
  if (id) url.searchParams.set(URL_PARAM, id);
  else url.searchParams.delete(URL_PARAM);
  window.history.replaceState(null, "", url);
}

/**
 * Owns the open dataset and the visible page of rows.
 *
 * The dataset id is mirrored into the URL (?dataset=…) so a refresh, or a
 * link shared with a teammate, reopens the same table.
 */
export function useDataset() {
  const [dataset, setDataset] = useState(null);
  const [restoring, setRestoring] = useState(() => Boolean(readDatasetIdFromUrl()));
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [highlight, setHighlight] = useState(false);
  const [table, setTable] = useState(null);
  const [tableLoading, setTableLoading] = useState(false);
  const [tableError, setTableError] = useState(null);

  // Reopen the dataset named in the URL, if any.
  useEffect(() => {
    const id = readDatasetIdFromUrl();
    if (!id) return;
    api
      .getDataset(id)
      .then((body) => setDataset(body.dataset))
      .catch(() => writeDatasetIdToUrl(null))
      .finally(() => setRestoring(false));
  }, []);

  useEffect(() => {
    if (!restoring) writeDatasetIdToUrl(dataset?.id ?? null);
  }, [dataset?.id, restoring]);

  // Any change to the dataset's history produces a new version key, which refetches rows.
  const operations = dataset?.operations ?? [];
  const versionKey = dataset ? `${dataset.id}:${operations.length}:${operations.at(-1)?.id ?? 0}` : null;

  useEffect(() => {
    if (!versionKey) return undefined;
    let cancelled = false;
    setTableLoading(true);
    setTableError(null);
    api
      .getRows(dataset.id, { page, pageSize, highlight })
      .then((body) => !cancelled && setTable(body))
      .catch((error) => !cancelled && setTableError(error))
      .finally(() => !cancelled && setTableLoading(false));
    return () => {
      cancelled = true;
    };
    // dataset.id is part of versionKey
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [versionKey, page, pageSize, highlight]);

  const open = useCallback((next) => {
    setDataset(next);
    setTable(null);
    setPage(1);
    setHighlight(false);
  }, []);

  const close = useCallback(() => {
    setDataset(null);
    setTable(null);
    setPage(1);
  }, []);

  /** Call after an operation; `showChanges` highlights the cells it touched. */
  const update = useCallback((next, { showChanges = true } = {}) => {
    setDataset(next);
    setHighlight(showChanges && next.operations.length > 0);
  }, []);

  const changePageSize = useCallback((size) => {
    setPageSize(size);
    setPage(1);
  }, []);

  return {
    dataset,
    restoring,
    table,
    tableLoading,
    tableError,
    page,
    pageSize,
    highlight,
    setPage,
    setPageSize: changePageSize,
    setHighlight,
    open,
    close,
    update,
  };
}
