import axios, { AxiosInstance, AxiosError } from 'axios';
import logger from './logger.js';

interface FetcherOptions {
  timeout?: number;
  maxRetries?: number;
  delayMs?: number;
}

const DEFAULT_TIMEOUT = 10_000;
const DEFAULT_MAX_RETRIES = 3;
const DEFAULT_DELAY_MS = 500;

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function isRetryable(error: AxiosError): boolean {
  if (error.code === 'ECONNABORTED' || error.code === 'ETIMEDOUT') return true;
  const status = error.response?.status;
  if (status && status >= 500) return true;
  return false;
}

export class Fetcher {
  private client: AxiosInstance;
  private maxRetries: number;
  private delayMs: number;
  private lastRequestTime = 0;

  constructor(options: FetcherOptions = {}) {
    this.maxRetries = options.maxRetries ?? DEFAULT_MAX_RETRIES;
    this.delayMs = options.delayMs ?? DEFAULT_DELAY_MS;
    this.client = axios.create({
      timeout: options.timeout ?? DEFAULT_TIMEOUT,
      headers: {
        'User-Agent':
          'Mozilla/5.0 (compatible; SKKUverseCrawler/1.0)',
      },
      responseType: 'text',
    });
  }

  async fetchBinary(url: string): Promise<Buffer> {
    const now = Date.now();
    const elapsed = now - this.lastRequestTime;
    if (elapsed < this.delayMs) {
      await sleep(this.delayMs - elapsed);
    }

    let lastError: Error | null = null;

    for (let attempt = 1; attempt <= this.maxRetries; attempt++) {
      try {
        this.lastRequestTime = Date.now();
        const response = await this.client.get(url, { responseType: 'arraybuffer' });
        return Buffer.from(response.data);
      } catch (err) {
        const axiosErr = err as AxiosError;
        lastError = axiosErr;

        if (!isRetryable(axiosErr)) {
          logger.warn({ url, status: axiosErr.response?.status }, 'Non-retryable fetch error');
          throw axiosErr;
        }

        if (attempt < this.maxRetries) {
          const backoff = Math.pow(2, attempt - 1) * 1000;
          logger.warn(
            { url, attempt, backoff, code: axiosErr.code },
            'Retrying fetch'
          );
          await sleep(backoff);
        }
      }
    }

    logger.error({ url }, 'All fetch retries exhausted');
    throw lastError!;
  }

  async fetch(url: string): Promise<string> {
    const now = Date.now();
    const elapsed = now - this.lastRequestTime;
    if (elapsed < this.delayMs) {
      await sleep(this.delayMs - elapsed);
    }

    let lastError: Error | null = null;

    for (let attempt = 1; attempt <= this.maxRetries; attempt++) {
      try {
        this.lastRequestTime = Date.now();
        const response = await this.client.get<string>(url);
        return response.data;
      } catch (err) {
        const axiosErr = err as AxiosError;
        lastError = axiosErr;

        if (!isRetryable(axiosErr)) {
          logger.warn({ url, status: axiosErr.response?.status }, 'Non-retryable fetch error');
          throw axiosErr;
        }

        if (attempt < this.maxRetries) {
          const backoff = Math.pow(2, attempt - 1) * 1000;
          logger.warn(
            { url, attempt, backoff, code: axiosErr.code },
            'Retrying fetch'
          );
          await sleep(backoff);
        }
      }
    }

    logger.error({ url }, 'All fetch retries exhausted');
    throw lastError!;
  }
}
