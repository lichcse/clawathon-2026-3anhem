"use client";

import { useEffect, useState } from "react";
import { listBlocks, type BlockSpec } from "./api";

export type BlockCatalog = {
  byId: Record<string, BlockSpec>;
  all: BlockSpec[];
  loading: boolean;
  error: string | null;
};

export function useBlockCatalog(): BlockCatalog {
  const [all, setAll] = useState<BlockSpec[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    listBlocks()
      .then((blocks) => {
        if (!cancelled) {
          setAll(blocks);
          setLoading(false);
        }
      })
      .catch((e) => {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : String(e));
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const byId = Object.fromEntries(all.map((b) => [b.id, b]));
  return { byId, all, loading, error };
}
