/**
 * Save a Blob to the user's machine.
 *
 * Object URLs leak until revoked, and a <a download> that is never attached
 * to the document does not fire in Firefox — both mistakes are easy to make
 * twice, so the dance lives in one place.
 */
export function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

/** Open a Blob in a new tab, for "view" rather than "download". */
export function openBlob(blob: Blob): void {
  const url = URL.createObjectURL(blob);
  window.open(url, "_blank", "noopener");
  // Revoked late: revoking immediately races the new tab's load.
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}
