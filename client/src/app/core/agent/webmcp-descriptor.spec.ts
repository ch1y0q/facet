import type { Mock } from 'vitest';
import { EnvironmentInjector } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { WebMcpToolParts, registerWebMcpTools, toHex, toWebMcpDescriptor } from './webmcp-descriptor';

describe('webmcp-descriptor', () => {
  let execute: Mock;

  const parts = (name: string): WebMcpToolParts => ({
    name,
    description: `${name} description`,
    inputSchema: { type: 'object', properties: {} },
    annotations: { readOnlyHint: true },
    execute,
  });

  beforeEach(() => {
    execute = vi.fn(async () => 'done');
  });

  afterEach(() => {
    Reflect.deleteProperty(document, 'modelContext');
  });

  describe('toWebMcpDescriptor', () => {
    it('passes the tool parts through unchanged', () => {
      const input = parts('a');
      const descriptor = toWebMcpDescriptor(input) as unknown as WebMcpToolParts;
      expect(descriptor).toBe(input);
      expect(descriptor.name).toBe('a');
      expect(descriptor.annotations).toEqual({ readOnlyHint: true });
      expect(descriptor.inputSchema).toEqual({ type: 'object', properties: {} });
    });
  });

  describe('toHex', () => {
    it('renders lower-case zero-padded hex', () => {
      expect(toHex(new Uint8Array([0, 1, 15, 16, 171, 255]))).toBe('00010f10abff');
    });

    it('returns an empty string for no bytes', () => {
      expect(toHex(new Uint8Array([]))).toBe('');
    });
  });

  describe('registerWebMcpTools', () => {
    it('registers every descriptor on document.modelContext', async () => {
      const registerTool: Mock<(tool: unknown, options?: unknown) => Promise<void>> = vi.fn(async () => undefined);
      Object.defineProperty(document, 'modelContext', { value: { registerTool }, configurable: true });
      const injector = TestBed.inject(EnvironmentInjector);
      const results = await registerWebMcpTools([toWebMcpDescriptor(parts('a')), toWebMcpDescriptor(parts('b'))], injector) as PromiseSettledResult<unknown>[];
      expect(registerTool).toHaveBeenCalledTimes(2);
      expect(registerTool.mock.calls.map((c: unknown[]) => (c[0] as { name: string }).name)).toEqual(['a', 'b']);
      expect(results.map(r => r.status)).toEqual(['fulfilled', 'fulfilled']);
    });

    it('calls through to the handler when a registered tool executes', async () => {
      const registerTool: Mock<(tool: unknown, options?: unknown) => Promise<void>> = vi.fn(async () => undefined);
      Object.defineProperty(document, 'modelContext', { value: { registerTool }, configurable: true });
      await registerWebMcpTools([toWebMcpDescriptor(parts('a'))], TestBed.inject(EnvironmentInjector));
      const registered = registerTool.mock.calls[0][0] as { execute: (args: unknown, client: unknown) => Promise<string> };
      await expect(registered.execute({ q: 1 }, {})).resolves.toBe('done');
      expect(execute).toHaveBeenCalledTimes(1);
      expect(execute.mock.calls[0][0]).toEqual({ q: 1 });
    });

    it('does not stop the others when one registration fails', async () => {
      const registerTool: Mock<(tool: unknown, options?: unknown) => Promise<void>> = vi.fn(async (tool: unknown) => {
        if ((tool as { name: string }).name === 'bad') throw new Error('boom');
      });
      Object.defineProperty(document, 'modelContext', { value: { registerTool }, configurable: true });
      const results = await registerWebMcpTools(
        [toWebMcpDescriptor(parts('bad')), toWebMcpDescriptor(parts('good'))],
        TestBed.inject(EnvironmentInjector),
      ) as PromiseSettledResult<unknown>[];
      expect(registerTool).toHaveBeenCalledTimes(2);
      expect(results.map(r => r.status)).toEqual(['rejected', 'fulfilled']);
    });

    it('registers nothing and resolves when modelContext is absent', async () => {
      const results = await registerWebMcpTools([toWebMcpDescriptor(parts('a'))], TestBed.inject(EnvironmentInjector)) as PromiseSettledResult<unknown>[];
      expect(results.map(r => r.status)).toEqual(['fulfilled']);
      expect(execute).not.toHaveBeenCalled();
    });

    it('resolves with an empty list for no descriptors', async () => {
      await expect(registerWebMcpTools([], TestBed.inject(EnvironmentInjector))).resolves.toEqual([]);
    });
  });
});
