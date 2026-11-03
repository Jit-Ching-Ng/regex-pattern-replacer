/**
 * Thin client for the Django API.
 *
 * Every failure is normalised into an ApiError carrying the backend's
 * `{error: {code, message, details}}` body, so components can show
 * `error.message` without caring whether it was a network or server problem.
 */

const BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");

export class ApiError extends Error {
  constructor(message, { code = "error", status = 0, details = null } = {}) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
    this.details = details;
  }
}

function toApiError(status, body) {
  const error = body?.error;
  if (error?.message) {
    return new ApiError(error.message, { code: error.code, status, details: error.details });
  }
  if (status === 413) {
    return new ApiError("The file is too large for the server.", { code: "too_large", status });
  }
  return new ApiError(`The server responded with an unexpected error (${status}).`, { status });
}

async function request(path, { method = "GET", body, query } = {}) {
  const url = new URL(`${BASE_URL}/api${path}`, window.location.origin);
  Object.entries(query ?? {}).forEach(([key, value]) => {
    if (value !== undefined && value !== null) url.searchParams.set(key, String(value));
  });

  let response;
  try {
    response = await fetch(url, {
      method,
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new ApiError("Could not reach the server. Check your connection and try again.", {
      code: "network_error",
    });
  }

  const data = await response.json().catch(() => null);
  if (!response.ok) throw toApiError(response.status, data);
  return data;
}

/** Upload with progress reporting (fetch cannot report upload progress). */
export function uploadDataset(file, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    const form = new FormData();
    form.append("file", file);

    xhr.open("POST", `${BASE_URL}/api/datasets/`);
    xhr.responseType = "json";
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress?.(event.loaded / event.total);
    };
    xhr.onerror = () =>
      reject(new ApiError("The upload failed. Check your connection and try again.", { code: "network_error" }));
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) resolve(xhr.response);
      else reject(toApiError(xhr.status, xhr.response));
    };
    xhr.send(form);
  });
}

export const api = {
  health: () => request("/health/"),
  getDataset: (id) => request(`/datasets/${id}/`),
  deleteDataset: (id) => request(`/datasets/${id}/`, { method: "DELETE" }),
  getRows: (id, { page, pageSize, highlight }) =>
    request(`/datasets/${id}/rows/`, { query: { page, page_size: pageSize, highlight } }),

  suggestRegex: (id, body) => request(`/datasets/${id}/regex/suggest/`, { method: "POST", body }),
  previewRegex: (id, body) => request(`/datasets/${id}/regex/preview/`, { method: "POST", body }),
  applyRegex: (id, body) => request(`/datasets/${id}/regex/apply/`, { method: "POST", body }),
  transform: (id, body) => request(`/datasets/${id}/transform/`, { method: "POST", body }),

  undo: (id) => request(`/datasets/${id}/undo/`, { method: "POST" }),
  reset: (id) => request(`/datasets/${id}/reset/`, { method: "POST" }),
  exportUrl: (id, format) => `${BASE_URL}/api/datasets/${id}/export/?format=${format}`,
};
