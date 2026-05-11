import { useCallback, useEffect, useRef, useState } from 'react';
import { apiJson, apiPostJson } from '../api/client';
import { markdownToSafeChatHtml } from '../utils/chatHtml';
import { vi, suggestedPrompts } from '../content/copy/vi';
import type { ApiEdge, ApiNode } from '../graph/types';
import type { GraphController } from '../graph/useKgGraph';

const SESSIONS_KEY = 'kg_chat_sessions';
const CHAT_KEY = 'kg_chat_history';

interface Msg {
  role: 'user' | 'assistant';
  content: string;
}

interface Props {
  graph: GraphController | null;
  collapsed: boolean;
  onToggleCollapsed: () => void;
  onOpenAssistant: () => void;
}

export function AssistantPanel({
  graph,
  collapsed: _collapsed,
  onToggleCollapsed,
  onOpenAssistant,
}: Props) {
  const [history, setHistory] = useState<Msg[]>(() => {
    try {
      const raw = localStorage.getItem(CHAT_KEY);
      return raw ? JSON.parse(raw) : [];
    } catch {
      return [];
    }
  });
  const [sessions, setSessions] = useState<{ id: string; name: string }[]>(
    []
  );
  const [sessionSel, setSessionSel] = useState('');
  const [models, setModels] = useState<string[]>([]);
  const [model, setModel] = useState('');
  const [reasoning, setReasoning] = useState(true);
  const [input, setInput] = useState('');
  const [searchQ, setSearchQ] = useState('');
  const [searchHits, setSearchHits] = useState<
    { id: string; label: string; type?: string }[]
  >([]);
  const [searchOpen, setSearchOpen] = useState(false);
  const histRef = useRef<HTMLDivElement>(null);

  const [llmModalOpen, setLlmModalOpen] = useState(false);
  const [llmBackend, setLlmBackend] = useState('openai');
  const [llmBaseUrl, setLlmBaseUrl] = useState('');
  const [llmModelPick, setLlmModelPick] = useState('');
  const [llmModalModels, setLlmModalModels] = useState<string[]>([]);
  const [llmApiKeyInput, setLlmApiKeyInput] = useState('');
  const [llmClearKey, setLlmClearKey] = useState(false);
  const [llmModalMsg, setLlmModalMsg] = useState('');
  const [fetchingModels, setFetchingModels] = useState(false);

  const loadModelsFromApi = useCallback(
    () =>
      apiJson<{ models: string[]; current: string }>('/api/vllm/models')
        .then((d) => {
          const list = d.models?.length ? d.models : [d.current];
          setModels(list);
          const pref =
            localStorage.getItem('kg_selected_model') || d.current || list[0];
          setModel(pref && list.includes(pref) ? pref : list[0]);
        })
        .catch(() => setModels([])),
    []
  );

  useEffect(() => {
    try {
      const s = JSON.parse(localStorage.getItem(SESSIONS_KEY) || '{}');
      const list = (s.sessions || []).map(
        (x: { id: string; name: string }) => ({
          id: x.id,
          name: x.name,
        })
      );
      setSessions(list);
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    void loadModelsFromApi();
  }, [loadModelsFromApi]);

  const openLlmModal = () => {
    setLlmModalMsg('');
    setLlmApiKeyInput('');
    setLlmClearKey(false);
    setLlmModalOpen(true);
    void apiJson<{
      backend: string;
      base_url: string;
      model: string;
      models: string[];
    }>('/api/llm/settings')
      .then((d) => {
        setLlmBackend(d.backend || 'openai');
        setLlmBaseUrl(d.base_url || '');
        setLlmModelPick(d.model || '');
        setLlmModalModels(d.models?.length ? d.models : [d.model]);
      })
      .catch(() => {
        setLlmModalMsg(vi.loadFailed);
      });
  };

  const saveLlmSettings = async () => {
    setLlmModalMsg('');
    const m = llmModelPick.trim() || model;
    const body: Record<string, string | boolean> = {
      backend: llmBackend,
      base_url: llmBaseUrl.trim(),
      model: m,
    };
    if (llmClearKey) body.clear_api_key = true;
    else if (llmApiKeyInput.trim()) body.api_key = llmApiKeyInput.trim();
    try {
      const out = await apiPostJson<{
        ok?: boolean;
        error?: string;
        models?: string[];
        model?: string;
      }>('/api/llm/settings', body);
      if (out.error) {
        setLlmModalMsg(`${vi.toastErrorPrefix}: ${out.error}`);
        return;
      }
      if (out.models?.length) {
        setLlmModalModels(out.models);
        setModels(out.models);
        const pick = out.model && out.models.includes(out.model) ? out.model : out.models[0];
        setLlmModelPick(pick);
        setModel(pick);
        localStorage.setItem('kg_selected_model', pick);
      } else {
        await loadModelsFromApi();
      }
      setLlmModalMsg(vi.llmSettingsSaved);
      setLlmApiKeyInput('');
      setLlmClearKey(false);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setLlmModalMsg(`${vi.toastErrorPrefix}: ${msg}`);
    }
  };

  const handleFetchModels = async () => {
    const baseUrl = llmBaseUrl.trim();
    if (!baseUrl) {
      setLlmModalMsg(vi.llmBaseUrlRequired);
      return;
    }
    setFetchingModels(true);
    setLlmModalMsg('');
    try {
      const body: Record<string, string> = {
        base_url: baseUrl,
        backend: llmBackend,
      };
      const apiKey = llmApiKeyInput.trim();
      if (apiKey) body.api_key = apiKey;
      const res = await apiPostJson<{
        models?: string[];
        error?: string;
      }>('/api/llm/fetch-models', body);
      if (res.error) {
        setLlmModalMsg(`${vi.toastErrorPrefix}: ${res.error}`);
        return;
      }
      if (res.models?.length) {
        setLlmModalModels(res.models);
        setLlmModalMsg(`Đã lấy ${res.models.length} model(s)`);
      } else {
        setLlmModalMsg(vi.llmNoModelsFound);
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setLlmModalMsg(`${vi.toastErrorPrefix}: ${msg}`);
    } finally {
      setFetchingModels(false);
    }
  };

  useEffect(() => {
    localStorage.setItem(CHAT_KEY, JSON.stringify(history));
    histRef.current?.scrollTo({ top: histRef.current.scrollHeight });
  }, [history]);

  const handleSend = async () => {
    const q = input.trim();
    if (!q || !graph) return;
    const userMsg: Msg = { role: 'user', content: q };
    const nextHist = [...history, userMsg];
    setHistory([...nextHist, { role: 'assistant', content: '__loading__' }]);
    setInput('');

    try {
      const data = await apiPostJson<{
        answer?: string;
        error?: string;
        nodes?: ApiNode[];
        edges?: ApiEdge[];
        graphs?: { nodes: ApiNode[]; edges: ApiEdge[] }[];
        steps?: string[];
        cypher?: string;
      }>('/api/query', {
        query: q,
        history: nextHist.map((m) => ({ role: m.role, content: m.content })),
        reasoning,
        model,
      });

      setHistory((h) => {
        const nh = h.filter((m) => m.content !== '__loading__');
        if (data.error) nh.push({ role: 'assistant', content: `Lỗi: ${data.error}` });
        else nh.push({ role: 'assistant', content: data.answer || '—' });
        return nh;
      });

      window.dispatchEvent(
        new CustomEvent('kg-query-ui', {
          detail: { steps: data.steps, cypher: data.cypher },
        })
      );

      let nodes = data.nodes;
      let edges = data.edges;
      if ((!nodes || !nodes.length) && data.graphs?.length) {
        for (const g of data.graphs) {
          if (g.nodes?.length) {
            nodes = g.nodes;
            edges = g.edges || [];
            break;
          }
        }
      }
      if (nodes?.length) graph.drawQueryGraph(nodes, edges || []);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setHistory((h) => {
        const nh = h.filter((m) => m.content !== '__loading__');
        nh.push({ role: 'assistant', content: `Lỗi: ${msg}` });
        return nh;
      });
    }
  };

  const saveSession = () => {
    if (!history.length) return;
    const d = new Date();
    const name = `Phiên ${d.toLocaleDateString('vi-VN')} ${d.toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' })}`;
    const id = String(Date.now());
    try {
      const raw = localStorage.getItem(SESSIONS_KEY);
      const store = raw ? JSON.parse(raw) : { sessions: [] };
      store.sessions = [{ id, name, messages: history }, ...store.sessions].slice(
        0,
        40
      );
      localStorage.setItem(SESSIONS_KEY, JSON.stringify(store));
      setSessions(
        store.sessions.map((s: { id: string; name: string }) => ({
          id: s.id,
          name: s.name,
        }))
      );
    } catch {
      /* ignore */
    }
  };

  const loadSession = (id: string) => {
    if (!id) return;
    try {
      const raw = localStorage.getItem(SESSIONS_KEY);
      const store = raw ? JSON.parse(raw) : { sessions: [] };
      const s = store.sessions?.find((x: { id: string }) => x.id === id);
      if (s?.messages) {
        setHistory(s.messages);
        localStorage.setItem(CHAT_KEY, JSON.stringify(s.messages));
      }
    } catch {
      /* ignore */
    }
  };

  const clearSessions = () => {
    if (!confirm('Xóa toàn bộ lịch sử?')) return;
    localStorage.removeItem(SESSIONS_KEY);
    localStorage.removeItem(CHAT_KEY);
    setHistory([]);
    setSessions([]);
    setSessionSel('');
  };

  useEffect(() => {
    const t = window.setTimeout(async () => {
      const q = searchQ.trim();
      if (q.length < 2) {
        setSearchHits([]);
        return;
      }
      try {
        const d = await apiJson<{ results: { id: string; label?: string; type?: string }[] }>(
          `/api/search?q=${encodeURIComponent(q)}`
        );
        setSearchHits(
          (d.results?.slice(0, 8) || []).map((h) => ({
            id: h.id,
            label: h.label ?? h.id,
            type: h.type,
          }))
        );
        setSearchOpen(true);
      } catch {
        setSearchHits([]);
      }
    }, 160);
    return () => window.clearTimeout(t);
  }, [searchQ]);

  const pickSearch = (id: string) => {
    setSearchQ('');
    setSearchOpen(false);
    window.dispatchEvent(new CustomEvent('kg-search-pick', { detail: id }));
  };

  return (
    <div className="assistant-shell">
      <button
        type="button"
        className="panel-edge-toggle right"
        title={vi.rightToggle}
        onClick={onToggleCollapsed}
      >
        <span className="panel-edge-glyph" aria-hidden>
          ›
        </span>
      </button>

      <div className="right-panel-inner">
        <div className="assist-intro">
          <span className="assist-kicker">{vi.assistantKicker}</span>
          <p className="assist-hl">{vi.assistantHeadline}</p>
        </div>

        <div className="rp-head">
          <div className="rp-row">
            <strong>{vi.assistantTitle}</strong>
            <div className="rp-actions">
              <button
                type="button"
                className="ico-btn"
                title={vi.llmSettingsOpen}
                onClick={openLlmModal}
              >
                LLM
              </button>
              <select
                className="select-mini"
                value={sessionSel}
                onChange={(e) => {
                  setSessionSel(e.target.value);
                  loadSession(e.target.value);
                }}
              >
                <option value="">{vi.sessionPlaceholder}</option>
                {sessions.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </select>
              <button type="button" className="ico-btn" title={vi.saveSession} onClick={saveSession}>
                Lưu
              </button>
              <button type="button" className="ico-btn" title={vi.clearSessions} onClick={clearSessions}>
                Xóa
              </button>
            </div>
          </div>
          <div className="rp-toolbar">
            <select
              className="select-mini flex"
              value={model}
              onChange={(e) => {
                setModel(e.target.value);
                localStorage.setItem('kg_selected_model', e.target.value);
              }}
            >
              {models.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
            <label className="chk">
              <input
                type="checkbox"
                checked={reasoning}
                onChange={(e) => setReasoning(e.target.checked)}
              />{' '}
              {vi.reasoningToggle}
            </label>
          </div>

          <div className="search-shell">
            <input
              className="search-input"
              placeholder={vi.searchPlaceholder}
              value={searchQ}
              onChange={(e) => setSearchQ(e.target.value)}
              onFocus={() => setSearchOpen(true)}
            />
            {searchOpen && searchHits.length > 0 ? (
              <div className="search-dd">
                {searchHits.map((h) => (
                  <button
                    type="button"
                    key={h.id}
                    className="search-item"
                    onClick={() => pickSearch(h.id)}
                  >
                    <span className={`tag ${h.type === 'Person' ? 'pe' : 'co'}`}>
                      {h.type === 'Person' ? vi.legendPerson : vi.legendCompany}
                    </span>
                    {h.label || h.id}
                  </button>
                ))}
              </div>
            ) : null}
          </div>
        </div>

        <div className="chat-hist" ref={histRef}>
          {history.length === 0 ? (
            <p className="muted">{vi.chatWelcome}</p>
          ) : null}
          {history.map((m, i) =>
            m.content === '__loading__' ? (
              <div key={i} className="bot-msg loading">
                {vi.loadingOverlay}
              </div>
            ) : m.role === 'user' ? (
              <div key={i} className="user-msg">
                {m.content}
              </div>
            ) : (
              <div
                key={i}
                className="bot-msg"
                dangerouslySetInnerHTML={{
                  __html: markdownToSafeChatHtml(m.content),
                }}
              />
            )
          )}
        </div>

        <div className="chat-input-row">
          <div className="chat-composer">
            <input
              className="chat-inp"
              placeholder={vi.chatPlaceholder}
              aria-label={vi.chatPlaceholder}
              value={input}
              onKeyDown={(e) => e.key === 'Enter' && handleSend()}
              onChange={(e) => setInput(e.target.value)}
            />
          </div>
          <button type="button" className="btn-send" onClick={handleSend}>
            {vi.send}
          </button>
        </div>

        <div className="prompt-grid">
          {suggestedPrompts.slice(0, 5).map((p) => (
            <button
              type="button"
              key={p.slice(0, 24)}
              className="prompt-chip"
              onClick={() => {
                setInput(p);
                onOpenAssistant();
              }}
            >
              {p.length > 96 ? `${p.slice(0, 96)}…` : p}
            </button>
          ))}
        </div>
      </div>

      {llmModalOpen ? (
        <div
          className="llm-modal-overlay"
          role="presentation"
          onClick={() => setLlmModalOpen(false)}
        >
          <div
            className="llm-modal neu-panel"
            role="dialog"
            aria-labelledby="llm-modal-title"
            onClick={(e) => e.stopPropagation()}
          >
            <header className="llm-modal-hd">
              <h2 id="llm-modal-title">{vi.llmSettingsTitle}</h2>
              <button
                type="button"
                className="ndp-x"
                aria-label={vi.llmCancel}
                onClick={() => setLlmModalOpen(false)}
              >
                ×
              </button>
            </header>
            <div className="llm-modal-bd">
              <label className="llm-field">
                <span>{vi.llmBackend}</span>
                <select
                  className="select-mini llm-select-wide"
                  value={llmBackend}
                  onChange={(e) => setLlmBackend(e.target.value)}
                >
                  <option value="openai">openai (OpenAI-compatible)</option>
                  <option value="vllm">vllm</option>
                  <option value="openai_compat">openai_compat</option>
                  <option value="ollama">ollama</option>
                </select>
              </label>
              <label className="llm-field">
                <span>{vi.llmBaseUrl}</span>
                <input
                  className="search-input"
                  value={llmBaseUrl}
                  onChange={(e) => setLlmBaseUrl(e.target.value)}
                  placeholder="http://host:port"
                />
              </label>
              <label className="llm-field">
                <span>{vi.llmModel}</span>
                <div className="llm-model-row">
                  <select
                    className="select-mini llm-select-wide"
                    value={llmModelPick}
                    onChange={(e) => setLlmModelPick(e.target.value)}
                  >
                    {(llmModalModels.length ? llmModalModels : [llmModelPick || model]).map(
                      (x) => (
                        <option key={x} value={x}>
                          {x}
                        </option>
                      )
                    )}
                  </select>
                  <button
                    type="button"
                    className="ico-btn llm-fetch-btn"
                    disabled={fetchingModels}
                    onClick={() => void handleFetchModels()}
                    title={vi.llmFetchModels}
                  >
                    {fetchingModels ? vi.llmFetchingModels : vi.llmFetchModels}
                  </button>
                </div>
              </label>
              <label className="llm-field">
                <span>{vi.llmApiKey}</span>
                <input
                  className="search-input"
                  type="password"
                  autoComplete="off"
                  value={llmApiKeyInput}
                  onChange={(e) => setLlmApiKeyInput(e.target.value)}
                  placeholder={vi.llmApiKeyHint}
                />
              </label>
              <p className="llm-hint muted">{vi.llmApiKeyHint}</p>
              <label className="llm-field chk llm-row-chk">
                <input
                  type="checkbox"
                  checked={llmClearKey}
                  onChange={(e) => setLlmClearKey(e.target.checked)}
                />{' '}
                {vi.llmClearApiKey}
              </label>
              {llmModalMsg ? <p className="llm-status">{llmModalMsg}</p> : null}
            </div>
            <footer className="llm-modal-ft">
              <button type="button" className="ico-btn" onClick={() => setLlmModalOpen(false)}>
                {vi.llmCancel}
              </button>
              <button type="button" className="btn-send" onClick={() => void saveLlmSettings()}>
                {vi.llmSave}
              </button>
            </footer>
          </div>
        </div>
      ) : null}
    </div>
  );
}
