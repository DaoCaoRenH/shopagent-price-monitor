/** Owns a request slot. An old response can never commit into a newer selection. */
export class LatestRequest {
    private revision = 0
    private controller: AbortController | null = null
    begin() {
        this.cancel()
        this.controller = new AbortController()
        return { revision: this.revision, signal: this.controller.signal }
    }
    current(revision: number) {
        return this.revision === revision && !this.controller?.signal.aborted
    }
    cancel() {
        this.controller?.abort()
        this.revision += 1
    }
}
