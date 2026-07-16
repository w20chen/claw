declare module "@openclaw/plugin-sdk" {
  export type HookApi = {
    on(name: string, handler: (event: unknown, context?: unknown) => unknown | Promise<unknown>): void;
    getConfig?(): unknown;
    logger?: {
      error(message: string, data?: unknown): void;
      warn(message: string, data?: unknown): void;
      info(message: string, data?: unknown): void;
      debug(message: string, data?: unknown): void;
    };
  };

  export function definePluginEntry(factory: (api: HookApi) => void | Promise<void>): unknown;
}
