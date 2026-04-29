// ============================================
// DIAGRAM VIEWER ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬ï¿½ Miro-style Canvas App
// ============================================

const canvas = document.getElementById('canvas');
const ctx = canvas.getContext('2d');

// ---- State ----
const state = {
  shapes: [],
  connections: [],
  selected: null,
  selectedIds: new Set(),
  hoveredHandle: null,
  tool: 'select', // select, rect, ellipse, diamond, text, line
  camera: { x: 0, y: 0, zoom: 1 },
  drag: null,
  resize: null,
  lineDrawing: null,
  selectionBox: null,
  panning: false,
  panStart: null,
  undoStack: [],
  redoStack: [],
  idCounter: 1,
  fillColor: '#4A90D9',
  strokeColor: '#2C3E50',
  strokeWidth: 2,
  gridSize: 30,
};

// ---- Helpers ----
function uid() { return 'shape_' + (state.idCounter++); }

function screenToWorld(sx, sy) {
  return {
    x: (sx - state.camera.x) / state.camera.zoom,
    y: (sy - state.camera.y) / state.camera.zoom
  };
}

function worldToScreen(wx, wy) {
  return {
    x: wx * state.camera.zoom + state.camera.x,
    y: wy * state.camera.zoom + state.camera.y
  };
}

function cloneState() {
  return JSON.parse(JSON.stringify({ shapes: state.shapes, connections: state.connections, idCounter: state.idCounter }));
}

function pushUndo() {
  state.undoStack.push(cloneState());
  if (state.undoStack.length > 50) state.undoStack.shift();
  state.redoStack = [];
}

function undo() {
  if (!state.undoStack.length) return;
  state.redoStack.push(cloneState());
  const prev = state.undoStack.pop();
  state.shapes = prev.shapes;
  state.connections = prev.connections;
  state.idCounter = prev.idCounter;
  state.selected = null;
  state.selectedIds.clear();
  render();
}

function redo() {
  if (!state.redoStack.length) return;
  state.undoStack.push(cloneState());
  const next = state.redoStack.pop();
  state.shapes = next.shapes;
  state.connections = next.connections;
  state.idCounter = next.idCounter;
  state.selected = null;
  state.selectedIds.clear();
  render();
}

// ---- Shape Utilities ----
function shapeContains(s, wx, wy) {
  if (s.type === 'rect' || s.type === 'text') {
    return wx >= s.x && wx <= s.x + s.w && wy >= s.y && wy <= s.y + s.h;
  } else if (s.type === 'ellipse') {
    const cx = s.x + s.w / 2, cy = s.y + s.h / 2;
    const rx = s.w / 2, ry = s.h / 2;
    return ((wx - cx) ** 2) / (rx ** 2) + ((wy - cy) ** 2) / (ry ** 2) <= 1;
  } else if (s.type === 'diamond') {
    const cx = s.x + s.w / 2, cy = s.y + s.h / 2;
    return Math.abs(wx - cx) / (s.w / 2) + Math.abs(wy - cy) / (s.h / 2) <= 1;
  }
  return false;
}

function getShapeCenter(s) {
  return { x: s.x + s.w / 2, y: s.y + s.h / 2 };
}

function getShapeAnchors(s) {
  const cx = s.x + s.w / 2, cy = s.y + s.h / 2;
  return [
    { id: 'top', x: cx, y: s.y },
    { id: 'bottom', x: cx, y: s.y + s.h },
    { id: 'left', x: s.x, y: cy },
    { id: 'right', x: s.x + s.w, y: cy },
  ];
}

function getResizeHandles(s) {
  const sz = 8 / state.camera.zoom;
  return [
    { id: 'nw', x: s.x, y: s.y, cursor: 'nwse-resize' },
    { id: 'ne', x: s.x + s.w, y: s.y, cursor: 'nesw-resize' },
    { id: 'sw', x: s.x, y: s.y + s.h, cursor: 'nesw-resize' },
    { id: 'se', x: s.x + s.w, y: s.y + s.h, cursor: 'nwse-resize' },
    { id: 'n', x: s.x + s.w / 2, y: s.y, cursor: 'ns-resize' },
    { id: 's', x: s.x + s.w / 2, y: s.y + s.h, cursor: 'ns-resize' },
    { id: 'e', x: s.x + s.w, y: s.y + s.h / 2, cursor: 'ew-resize' },
    { id: 'w', x: s.x, y: s.y + s.h / 2, cursor: 'ew-resize' },
  ];
}

function hitHandle(s, wx, wy) {
  const tol = 8 / state.camera.zoom;
  for (const h of getResizeHandles(s)) {
    if (Math.abs(wx - h.x) < tol && Math.abs(wy - h.y) < tol) return h;
  }
  return null;
}

function hitAnchor(s, wx, wy) {
  const tol = 12 / state.camera.zoom;
  for (const a of getShapeAnchors(s)) {
    if (Math.abs(wx - a.x) < tol && Math.abs(wy - a.y) < tol) return a;
  }
  return null;
}

function findShapeAt(wx, wy) {
  for (let i = state.shapes.length - 1; i >= 0; i--) {
    if (shapeContains(state.shapes[i], wx, wy)) return state.shapes[i];
  }
  return null;
}

function findConnectionAt(wx, wy) {
  const tol = 6 / state.camera.zoom;
  for (let i = state.connections.length - 1; i >= 0; i--) {
    const c = state.connections[i];
    const from = state.shapes.find(s => s.id === c.fromId);
    const to = state.shapes.find(s => s.id === c.toId);
    if (!from || !to) continue;
    const a = getShapeCenter(from), b = getShapeCenter(to);
    const dist = pointToSegDist(wx, wy, a.x, a.y, b.x, b.y);
    if (dist < tol) return c;
  }
  return null;
}

function pointToSegDist(px, py, ax, ay, bx, by) {
  const dx = bx - ax, dy = by - ay;
  const len2 = dx * dx + dy * dy;
  if (len2 === 0) return Math.hypot(px - ax, py - ay);
  let t = ((px - ax) * dx + (py - ay) * dy) / len2;
  t = Math.max(0, Math.min(1, t));
  return Math.hypot(px - (ax + t * dx), py - (ay + t * dy));
}

// ---- Rendering ----
function resizeCanvas() {
  canvas.width = window.innerWidth * devicePixelRatio;
  canvas.height = window.innerHeight * devicePixelRatio;
  canvas.style.width = window.innerWidth + 'px';
  canvas.style.height = window.innerHeight + 'px';
  ctx.scale(devicePixelRatio, devicePixelRatio);
  render();
}

function drawGrid() {
  const gs = state.gridSize * state.camera.zoom;
  if (gs < 8) return; // too small, skip
  const offX = state.camera.x % gs;
  const offY = state.camera.y % gs;
  ctx.strokeStyle = 'rgba(0,0,0,0.08)';
  ctx.lineWidth = 1;
  ctx.beginPath();
  for (let x = offX; x < window.innerWidth; x += gs) {
    ctx.moveTo(x, 0);
    ctx.lineTo(x, window.innerHeight);
  }
  for (let y = offY; y < window.innerHeight; y += gs) {
    ctx.moveTo(0, y);
    ctx.lineTo(window.innerWidth, y);
  }
  ctx.stroke();
}

function drawShape(s) {
  ctx.save();
  ctx.translate(state.camera.x, state.camera.y);
  ctx.scale(state.camera.zoom, state.camera.zoom);

  ctx.globalAlpha = s.opacity ?? 1;
  ctx.fillStyle = s.fill || '#4A90D9';
  ctx.strokeStyle = s.stroke || '#2C3E50';
  ctx.lineWidth = s.strokeWidth || 2;

  if (s.type === 'rect') {
    const r = 6;
    ctx.beginPath();
    ctx.moveTo(s.x + r, s.y);
    ctx.lineTo(s.x + s.w - r, s.y);
    ctx.quadraticCurveTo(s.x + s.w, s.y, s.x + s.w, s.y + r);
    ctx.lineTo(s.x + s.w, s.y + s.h - r);
    ctx.quadraticCurveTo(s.x + s.w, s.y + s.h, s.x + s.w - r, s.y + s.h);
    ctx.lineTo(s.x + r, s.y + s.h);
    ctx.quadraticCurveTo(s.x, s.y + s.h, s.x, s.y + s.h - r);
    ctx.lineTo(s.x, s.y + r);
    ctx.quadraticCurveTo(s.x, s.y, s.x + r, s.y);
    ctx.closePath();
    ctx.fill();
    ctx.stroke();
  } else if (s.type === 'ellipse') {
    ctx.beginPath();
    ctx.ellipse(s.x + s.w / 2, s.y + s.h / 2, Math.abs(s.w / 2), Math.abs(s.h / 2), 0, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
  } else if (s.type === 'diamond') {
    const cx = s.x + s.w / 2, cy = s.y + s.h / 2;
    ctx.beginPath();
    ctx.moveTo(cx, s.y);
    ctx.lineTo(s.x + s.w, cy);
    ctx.lineTo(cx, s.y + s.h);
    ctx.lineTo(s.x, cy);
    ctx.closePath();
    ctx.fill();
    ctx.stroke();
  } else if (s.type === 'text') {
    // background
    ctx.fillStyle = 'rgba(74,144,217,0.08)';
    ctx.fillRect(s.x, s.y, s.w, s.h);
    // text
    ctx.fillStyle = s.fill || '#e0e0e0';
    ctx.font = `${s.fontSize || 16}px -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif`;
    ctx.textBaseline = 'top';
    const lines = wrapText(s.text || 'Text', s.w - 12, ctx);
    lines.forEach((line, i) => {
      ctx.fillText(line, s.x + 6, s.y + 6 + i * (s.fontSize || 16) * 1.3);
    });
  }

  // Draw text label on shapes (except text type)
  if (s.type !== 'text' && s.text) {
    ctx.fillStyle = '#fff';
    ctx.font = `${s.fontSize || 14}px -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(s.text, s.x + s.w / 2, s.y + s.h / 2);
    ctx.textAlign = 'start';
  }

  ctx.restore();
}

function wrapText(text, maxW, c) {
  const words = text.split(' ');
  const lines = [];
  let line = '';
  for (const w of words) {
    const test = line ? line + ' ' + w : w;
    if (c.measureText(test).width > maxW && line) {
      lines.push(line);
      line = w;
    } else {
      line = test;
    }
  }
  if (line) lines.push(line);
  return lines;
}

function drawConnection(c) {
  const from = state.shapes.find(s => s.id === c.fromId);
  const to = state.shapes.find(s => s.id === c.toId);
  if (!from || !to) return;

  const a = getShapeCenter(from);
  const b = getShapeCenter(to);

  ctx.save();
  ctx.translate(state.camera.x, state.camera.y);
  ctx.scale(state.camera.zoom, state.camera.zoom);

  ctx.strokeStyle = c.color || '#4a90d9';
  ctx.lineWidth = c.width || 2;
  ctx.setLineDash(c.dashed ? [8, 4] : []);

  ctx.beginPath();
  ctx.moveTo(a.x, a.y);
  ctx.lineTo(b.x, b.y);
  ctx.stroke();
  ctx.setLineDash([]);

  // Arrow head
  const angle = Math.atan2(b.y - a.y, b.x - a.x);
  const headLen = 12;
  ctx.fillStyle = c.color || '#4a90d9';
  ctx.beginPath();
  ctx.moveTo(b.x, b.y);
  ctx.lineTo(b.x - headLen * Math.cos(angle - 0.4), b.y - headLen * Math.sin(angle - 0.4));
  ctx.lineTo(b.x - headLen * Math.cos(angle + 0.4), b.y - headLen * Math.sin(angle + 0.4));
  ctx.closePath();
  ctx.fill();

  ctx.restore();
}

function drawSelection(s) {
  ctx.save();
  ctx.translate(state.camera.x, state.camera.y);
  ctx.scale(state.camera.zoom, state.camera.zoom);

  // Selection outline
  ctx.strokeStyle = '#4a90d9';
  ctx.lineWidth = 2 / state.camera.zoom;
  ctx.setLineDash([6 / state.camera.zoom, 4 / state.camera.zoom]);
  ctx.strokeRect(s.x - 4, s.y - 4, s.w + 8, s.h + 8);
  ctx.setLineDash([]);

  // Resize handles
  const handles = getResizeHandles(s);
  const hsz = 5 / state.camera.zoom;
  ctx.fillStyle = '#fff';
  ctx.strokeStyle = '#4a90d9';
  ctx.lineWidth = 1.5 / state.camera.zoom;
  for (const h of handles) {
    ctx.fillRect(h.x - hsz, h.y - hsz, hsz * 2, hsz * 2);
    ctx.strokeRect(h.x - hsz, h.y - hsz, hsz * 2, hsz * 2);
  }

  // Connection anchors (when line tool)
  if (state.tool === 'line') {
    const anchors = getShapeAnchors(s);
    const ar = 5 / state.camera.zoom;
    ctx.fillStyle = '#4a90d9';
    for (const a of anchors) {
      ctx.beginPath();
      ctx.arc(a.x, a.y, ar, 0, Math.PI * 2);
      ctx.fill();
    }
  }

  ctx.restore();
}

function drawSelectionBox() {
  if (!state.selectionBox) return;
  const sb = state.selectionBox;
  ctx.save();
  ctx.fillStyle = 'rgba(74,144,217,0.1)';
  ctx.strokeStyle = '#4a90d9';
  ctx.lineWidth = 1;
  ctx.setLineDash([4, 4]);
  const x = Math.min(sb.x1, sb.x2), y = Math.min(sb.y1, sb.y2);
  const w = Math.abs(sb.x2 - sb.x1), h = Math.abs(sb.y2 - sb.y1);
  ctx.fillRect(x, y, w, h);
  ctx.strokeRect(x, y, w, h);
  ctx.setLineDash([]);
  ctx.restore();
}

function drawLinePreview() {
  if (!state.lineDrawing) return;
  const ld = state.lineDrawing;
  ctx.save();
  ctx.translate(state.camera.x, state.camera.y);
  ctx.scale(state.camera.zoom, state.camera.zoom);
  ctx.strokeStyle = '#4a90d9';
  ctx.lineWidth = 2;
  ctx.setLineDash([6, 4]);
  ctx.beginPath();
  ctx.moveTo(ld.fromX, ld.fromY);
  ctx.lineTo(ld.toX, ld.toY);
  ctx.stroke();
  ctx.setLineDash([]);
  ctx.restore();
}

function render() {
  ctx.save();
  ctx.setTransform(devicePixelRatio, 0, 0, devicePixelRatio, 0, 0);
  ctx.clearRect(0, 0, window.innerWidth, window.innerHeight);

  // Background
  ctx.fillStyle = '#f0f2f5';
  ctx.fillRect(0, 0, window.innerWidth, window.innerHeight);

  drawGrid();

  // Connections
  state.connections.forEach(drawConnection);

  // Shapes
  state.shapes.forEach(drawShape);

  // Selection
  if (state.selected) drawSelection(state.selected);
  state.selectedIds.forEach(id => {
    const s = state.shapes.find(sh => sh.id === id);
    if (s && s !== state.selected) drawSelection(s);
  });

  // Anchors on hover when line tool
  if (state.tool === 'line') {
    state.shapes.forEach(s => {
      ctx.save();
      ctx.translate(state.camera.x, state.camera.y);
      ctx.scale(state.camera.zoom, state.camera.zoom);
      const anchors = getShapeAnchors(s);
      const ar = 4 / state.camera.zoom;
      ctx.fillStyle = 'rgba(74,144,217,0.5)';
      for (const a of anchors) {
        ctx.beginPath();
        ctx.arc(a.x, a.y, ar, 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.restore();
    });
  }

  drawLinePreview();
  drawSelectionBox();

  ctx.restore();

  // Zoom display
  document.getElementById('zoom-level').textContent = Math.round(state.camera.zoom * 100) + '%';
}

// ---- Event Handlers ----
canvas.addEventListener('mousedown', (e) => {
  const wx = (e.clientX - state.camera.x) / state.camera.zoom;
  const wy = (e.clientY - state.camera.y) / state.camera.zoom;

  // Middle mouse or space+click = pan
  if (e.button === 1 || (e.button === 0 && e.shiftKey && state.tool === 'select')) {
    state.panning = true;
    state.panStart = { x: e.clientX - state.camera.x, y: e.clientY - state.camera.y };
    canvas.style.cursor = 'grabbing';
    return;
  }

  if (e.button !== 0) return;

  // Tool: Line
  if (state.tool === 'line') {
    const shape = findShapeAt(wx, wy);
    if (shape) {
      const center = getShapeCenter(shape);
      state.lineDrawing = {
        fromId: shape.id,
        fromX: center.x, fromY: center.y,
        toX: wx, toY: wy
      };
    }
    return;
  }

  // Tool: Shape creation
  if (['rect', 'ellipse', 'diamond', 'text'].includes(state.tool)) {
    pushUndo();
    const newShape = {
      id: uid(),
      type: state.tool === 'text' ? 'text' : state.tool,
      x: wx, y: wy, w: 0, h: 0,
      fill: state.tool === 'text' ? '#e0e0e0' : state.fillColor,
      stroke: state.strokeColor,
      strokeWidth: state.strokeWidth,
      text: '',
      fontSize: state.tool === 'text' ? 16 : 14,
      opacity: 1,
    };
    state.shapes.push(newShape);
    state.selected = newShape;
    state.selectedIds.clear();
    state.selectedIds.add(newShape.id);
    state.drag = {
      type: 'create',
      shape: newShape,
      startX: wx, startY: wy
    };
    return;
  }

  // Tool: Select
  if (state.tool === 'select') {
    // Check resize handles first
    if (state.selected) {
      const handle = hitHandle(state.selected, wx, wy);
      if (handle) {
        pushUndo();
        state.resize = {
          shape: state.selected,
          handle: handle.id,
          origX: state.selected.x,
          origY: state.selected.y,
          origW: state.selected.w,
          origH: state.selected.h,
          startX: wx, startY: wy
        };
        canvas.style.cursor = handle.cursor;
        return;
      }
    }

    // Check shapes
    const shape = findShapeAt(wx, wy);
    if (shape) {
      if (e.ctrlKey || e.metaKey) {
        // Multi-select toggle
        if (state.selectedIds.has(shape.id)) {
          state.selectedIds.delete(shape.id);
          if (state.selected === shape) state.selected = null;
        } else {
          state.selectedIds.add(shape.id);
          state.selected = shape;
        }
      } else {
        if (!state.selectedIds.has(shape.id)) {
          state.selectedIds.clear();
          state.selectedIds.add(shape.id);
        }
        state.selected = shape;
      }
      pushUndo();
      state.drag = {
        type: 'move',
        startX: wx, startY: wy,
        offsets: [...state.selectedIds].map(id => {
          const s = state.shapes.find(sh => sh.id === id);
          return { id, dx: s.x - wx, dy: s.y - wy };
        })
      };
      // Bring to front
      const idx = state.shapes.indexOf(shape);
      if (idx >= 0) {
        state.shapes.splice(idx, 1);
        state.shapes.push(shape);
      }
    } else {
      // Check connections
      const conn = findConnectionAt(wx, wy);
      if (conn) {
        state.selected = null;
        state.selectedIds.clear();
        // highlight connection (visual feedback)
      } else {
        state.selected = null;
        state.selectedIds.clear();
        // Start selection box
        state.selectionBox = { x1: e.clientX, y1: e.clientY, x2: e.clientX, y2: e.clientY };
      }
    }
    updateProperties();
    render();
  }
});

canvas.addEventListener('mousemove', (e) => {
  const wx = (e.clientX - state.camera.x) / state.camera.zoom;
  const wy = (e.clientY - state.camera.y) / state.camera.zoom;

  // Panning
  if (state.panning && state.panStart) {
    state.camera.x = e.clientX - state.panStart.x;
    state.camera.y = e.clientY - state.panStart.y;
    render();
    return;
  }

  // Selection box
  if (state.selectionBox) {
    state.selectionBox.x2 = e.clientX;
    state.selectionBox.y2 = e.clientY;
    // Find shapes in box
    const x1 = Math.min(state.selectionBox.x1, state.selectionBox.x2);
    const y1 = Math.min(state.selectionBox.y1, state.selectionBox.y2);
    const x2 = Math.max(state.selectionBox.x1, state.selectionBox.x2);
    const y2 = Math.max(state.selectionBox.y1, state.selectionBox.y2);
    const wTL = screenToWorld(x1, y1);
    const wBR = screenToWorld(x2, y2);
    state.selectedIds.clear();
    state.shapes.forEach(s => {
      if (s.x + s.w >= wTL.x && s.x <= wBR.x && s.y + s.h >= wTL.y && s.y <= wBR.y) {
        state.selectedIds.add(s.id);
      }
    });
    render();
    return;
  }

  // Line drawing
  if (state.lineDrawing) {
    state.lineDrawing.toX = wx;
    state.lineDrawing.toY = wy;
    render();
    return;
  }

  // Creating shape
  if (state.drag && state.drag.type === 'create') {
    const s = state.drag.shape;
    const dx = wx - state.drag.startX;
    const dy = wy - state.drag.startY;
    s.w = dx;
    s.h = dy;
    render();
    return;
  }

  // Moving shape(s)
  if (state.drag && state.drag.type === 'move') {
    for (const off of state.drag.offsets) {
      const s = state.shapes.find(sh => sh.id === off.id);
      if (s) {
        s.x = wx + off.dx;
        s.y = wy + off.dy;
      }
    }
    render();
    return;
  }

  // Resizing
  if (state.resize) {
    const r = state.resize;
    const dx = wx - r.startX;
    const dy = wy - r.startY;
    const s = r.shape;

    if (r.handle.includes('e')) { s.w = Math.max(20, r.origW + dx); }
    if (r.handle.includes('w')) { s.x = r.origX + dx; s.w = Math.max(20, r.origW - dx); }
    if (r.handle.includes('s')) { s.h = Math.max(20, r.origH + dy); }
    if (r.handle.includes('n')) { s.y = r.origY + dy; s.h = Math.max(20, r.origH - dy); }

    render();
    return;
  }

  // Hover cursor
  if (state.tool === 'select' && state.selected) {
    const handle = hitHandle(state.selected, wx, wy);
    if (handle) {
      canvas.style.cursor = handle.cursor;
      return;
    }
  }
  if (state.tool === 'select') {
    const shape = findShapeAt(wx, wy);
    canvas.style.cursor = shape ? 'move' : 'default';
  } else if (state.tool === 'line') {
    canvas.style.cursor = 'crosshair';
  } else {
    canvas.style.cursor = 'crosshair';
  }
});

canvas.addEventListener('mouseup', (e) => {
  // Pan end
  if (state.panning) {
    state.panning = false;
    state.panStart = null;
    canvas.style.cursor = 'default';
    return;
  }

  // Selection box end
  if (state.selectionBox) {
    if (state.selectedIds.size === 1) {
      state.selected = state.shapes.find(s => state.selectedIds.has(s.id));
    }
    state.selectionBox = null;
    updateProperties();
    render();
    return;
  }

  // Line drawing end
  if (state.lineDrawing) {
    const wx = (e.clientX - state.camera.x) / state.camera.zoom;
    const wy = (e.clientY - state.camera.y) / state.camera.zoom;
    const target = findShapeAt(wx, wy);
    if (target && target.id !== state.lineDrawing.fromId) {
      pushUndo();
      state.connections.push({
        id: 'conn_' + (state.idCounter++),
        fromId: state.lineDrawing.fromId,
        toId: target.id,
        color: '#4a90d9',
        width: 2,
        dashed: false,
      });
    }
    state.lineDrawing = null;
    render();
    return;
  }

  // Finish creating shape
  if (state.drag && state.drag.type === 'create') {
    const s = state.drag.shape;
    // Normalize negative dimensions
    if (s.w < 0) { s.x += s.w; s.w = -s.w; }
    if (s.h < 0) { s.y += s.h; s.h = -s.h; }
    // Minimum size or click = default size
    if (s.w < 10 || s.h < 10) {
      if (s.type === 'text') {
        s.w = 160; s.h = 40;
      } else {
        s.w = 140; s.h = 90;
      }
    }
    state.drag = null;
    // For text shapes, open editor immediately
    if (s.type === 'text') {
      openTextEditor(s);
    }
    // Switch back to select
    setTool('select');
    updateProperties();
    render();
    return;
  }

  // Finish move/resize
  state.drag = null;
  state.resize = null;
  canvas.style.cursor = 'default';
  render();
});

// Double-click to edit text
canvas.addEventListener('dblclick', (e) => {
  const wx = (e.clientX - state.camera.x) / state.camera.zoom;
  const wy = (e.clientY - state.camera.y) / state.camera.zoom;
  const shape = findShapeAt(wx, wy);
  if (shape) {
    openTextEditor(shape);
  }
});

function openTextEditor(shape) {
  const editor = document.getElementById('text-editor');
  const sc = worldToScreen(shape.x, shape.y);
  editor.style.display = 'block';
  editor.style.left = sc.x + 'px';
  editor.style.top = sc.y + 'px';
  editor.style.width = (shape.w * state.camera.zoom) + 'px';
  editor.style.height = (shape.h * state.camera.zoom) + 'px';
  editor.style.fontSize = ((shape.fontSize || 14) * state.camera.zoom) + 'px';
  editor.value = shape.text || '';
  editor.focus();
  editor.select();

  const closeEditor = () => {
    pushUndo();
    shape.text = editor.value;
    editor.style.display = 'none';
    editor.removeEventListener('blur', closeEditor);
    editor.removeEventListener('keydown', keyHandler);
    render();
  };

  const keyHandler = (e) => {
    if (e.key === 'Escape') closeEditor();
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); closeEditor(); }
  };

  editor.addEventListener('blur', closeEditor);
  editor.addEventListener('keydown', keyHandler);
}

// Zoom with scroll
canvas.addEventListener('wheel', (e) => {
  e.preventDefault();
  const zoomFactor = e.deltaY < 0 ? 1.08 : 1 / 1.08;
  const newZoom = Math.max(0.1, Math.min(5, state.camera.zoom * zoomFactor));

  // Zoom toward mouse
  const mx = e.clientX, my = e.clientY;
  state.camera.x = mx - (mx - state.camera.x) * (newZoom / state.camera.zoom);
  state.camera.y = my - (my - state.camera.y) * (newZoom / state.camera.zoom);
  state.camera.zoom = newZoom;

  render();
}, { passive: false });

// Keyboard shortcuts
window.addEventListener('keydown', (e) => {
  // Don't capture when editing text
  if (document.getElementById('text-editor').style.display !== 'none') return;
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.tagName === 'SELECT') return;

  if (e.key === 'v' || e.key === 'V') setTool('select');
  if (e.key === 'r' || e.key === 'R') setTool('rect');
  if (e.key === 'e' || e.key === 'E') setTool('ellipse');
  if (e.key === 'd' && !e.ctrlKey && !e.metaKey) setTool('diamond');
  if (e.key === 't' || e.key === 'T') setTool('text');
  if (e.key === 'l' || e.key === 'L') setTool('line');

  if (e.key === 'Delete' || e.key === 'Backspace') {
    if (state.selectedIds.size) {
      pushUndo();
      state.shapes = state.shapes.filter(s => !state.selectedIds.has(s.id));
      state.connections = state.connections.filter(c => !state.selectedIds.has(c.fromId) && !state.selectedIds.has(c.toId));
      state.selected = null;
      state.selectedIds.clear();
      updateProperties();
      render();
    }
  }

  if ((e.ctrlKey || e.metaKey) && e.key === 'z') { e.preventDefault(); undo(); }
  if ((e.ctrlKey || e.metaKey) && (e.key === 'y' || (e.key === 'Z' && e.shiftKey))) { e.preventDefault(); redo(); }

  if ((e.ctrlKey || e.metaKey) && (e.key === 'd' || e.key === 'D')) {
    e.preventDefault();
    duplicateSelected();
  }

  if ((e.ctrlKey || e.metaKey) && e.key === 'a') {
    e.preventDefault();
    state.selectedIds.clear();
    state.shapes.forEach(s => state.selectedIds.add(s.id));
    if (state.shapes.length) state.selected = state.shapes[state.shapes.length - 1];
    render();
  }
});

function duplicateSelected() {
  if (!state.selectedIds.size) return;
  pushUndo();
  const newIds = new Set();
  const idMap = {};
  state.selectedIds.forEach(id => {
    const orig = state.shapes.find(s => s.id === id);
    if (!orig) return;
    const copy = { ...orig, id: uid(), x: orig.x + 20, y: orig.y + 20 };
    state.shapes.push(copy);
    newIds.add(copy.id);
    idMap[orig.id] = copy.id;
  });
  // Duplicate connections between selected shapes
  state.connections.forEach(c => {
    if (idMap[c.fromId] && idMap[c.toId]) {
      state.connections.push({
        ...c,
        id: 'conn_' + (state.idCounter++),
        fromId: idMap[c.fromId],
        toId: idMap[c.toId],
      });
    }
  });
  state.selectedIds = newIds;
  state.selected = state.shapes.find(s => newIds.has(s.id));
  render();
}

// ---- Toolbar ----
function setTool(tool) {
  state.tool = tool;
  document.querySelectorAll('.tool-btn').forEach(b => b.classList.remove('active'));
  const btnMap = { select: 'btn-select', rect: 'btn-rect', ellipse: 'btn-ellipse', diamond: 'btn-diamond', text: 'btn-text', line: 'btn-line' };
  const btn = document.getElementById(btnMap[tool]);
  if (btn) btn.classList.add('active');
}

document.getElementById('btn-select').addEventListener('click', () => setTool('select'));
document.getElementById('btn-rect').addEventListener('click', () => setTool('rect'));
document.getElementById('btn-ellipse').addEventListener('click', () => setTool('ellipse'));
document.getElementById('btn-diamond').addEventListener('click', () => setTool('diamond'));
document.getElementById('btn-text').addEventListener('click', () => setTool('text'));
document.getElementById('btn-line').addEventListener('click', () => setTool('line'));

document.getElementById('btn-delete').addEventListener('click', () => {
  if (state.selectedIds.size) {
    pushUndo();
    state.shapes = state.shapes.filter(s => !state.selectedIds.has(s.id));
    state.connections = state.connections.filter(c => !state.selectedIds.has(c.fromId) && !state.selectedIds.has(c.toId));
    state.selected = null;
    state.selectedIds.clear();
    updateProperties();
    render();
  }
});

document.getElementById('btn-clear').addEventListener('click', () => {
  pushUndo();
  state.shapes = [];
  state.connections = [];
  state.selected = null;
  state.selectedIds.clear();
  updateProperties();
  render();
});

document.getElementById('btn-duplicate').addEventListener('click', duplicateSelected);
document.getElementById('btn-undo').addEventListener('click', undo);
document.getElementById('btn-redo').addEventListener('click', redo);

document.getElementById('btn-zoom-in').addEventListener('click', () => {
  const center = { x: window.innerWidth / 2, y: window.innerHeight / 2 };
  const newZoom = Math.min(5, state.camera.zoom * 1.2);
  state.camera.x = center.x - (center.x - state.camera.x) * (newZoom / state.camera.zoom);
  state.camera.y = center.y - (center.y - state.camera.y) * (newZoom / state.camera.zoom);
  state.camera.zoom = newZoom;
  render();
});

document.getElementById('btn-zoom-out').addEventListener('click', () => {
  const center = { x: window.innerWidth / 2, y: window.innerHeight / 2 };
  const newZoom = Math.max(0.1, state.camera.zoom / 1.2);
  state.camera.x = center.x - (center.x - state.camera.x) * (newZoom / state.camera.zoom);
  state.camera.y = center.y - (center.y - state.camera.y) * (newZoom / state.camera.zoom);
  state.camera.zoom = newZoom;
  render();
});

document.getElementById('btn-zoom-fit').addEventListener('click', () => {
  if (!state.shapes.length) {
    state.camera = { x: 0, y: 0, zoom: 1 };
    render();
    return;
  }
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  state.shapes.forEach(s => {
    minX = Math.min(minX, s.x);
    minY = Math.min(minY, s.y);
    maxX = Math.max(maxX, s.x + s.w);
    maxY = Math.max(maxY, s.y + s.h);
  });
  const pad = 60;
  const cw = window.innerWidth - pad * 2;
  const ch = window.innerHeight - pad * 2;
  const sw = maxX - minX || 100;
  const sh = maxY - minY || 100;
  const zoom = Math.min(cw / sw, ch / sh, 2);
  state.camera.zoom = zoom;
  state.camera.x = (window.innerWidth - sw * zoom) / 2 - minX * zoom;
  state.camera.y = (window.innerHeight - sh * zoom) / 2 - minY * zoom;
  render();
});

document.getElementById('fill-color').addEventListener('input', (e) => {
  state.fillColor = e.target.value;
  if (state.selected && state.selected.type !== 'text') {
    pushUndo();
    state.selectedIds.forEach(id => {
      const s = state.shapes.find(sh => sh.id === id);
      if (s) s.fill = e.target.value;
    });
    render();
  }
});

document.getElementById('stroke-color').addEventListener('input', (e) => {
  state.strokeColor = e.target.value;
  if (state.selected) {
    pushUndo();
    state.selectedIds.forEach(id => {
      const s = state.shapes.find(sh => sh.id === id);
      if (s) s.stroke = e.target.value;
    });
    render();
  }
});

document.getElementById('stroke-width').addEventListener('change', (e) => {
  state.strokeWidth = parseInt(e.target.value);
  if (state.selected) {
    pushUndo();
    state.selectedIds.forEach(id => {
      const s = state.shapes.find(sh => sh.id === id);
      if (s) s.strokeWidth = parseInt(e.target.value);
    });
    render();
  }
});

// ---- Properties Panel ----
function updateProperties() {
  const panel = document.getElementById('properties-panel');
  if (!state.selected) {
    panel.style.display = 'none';
    return;
  }
  panel.style.display = 'block';
  document.getElementById('prop-text').value = state.selected.text || '';
  document.getElementById('prop-font-size').value = state.selected.fontSize || 14;
  document.getElementById('prop-opacity').value = state.selected.opacity ?? 1;
}

document.getElementById('prop-text').addEventListener('input', (e) => {
  if (state.selected) {
    state.selected.text = e.target.value;
    render();
  }
});

document.getElementById('prop-font-size').addEventListener('input', (e) => {
  if (state.selected) {
    state.selected.fontSize = parseInt(e.target.value) || 14;
    render();
  }
});

document.getElementById('prop-opacity').addEventListener('input', (e) => {
  if (state.selected) {
    state.selected.opacity = parseFloat(e.target.value);
    render();
  }
});

// ---- Context menu prevention ----
canvas.addEventListener('contextmenu', e => e.preventDefault());

// ---- Space bar panning ----
let spaceDown = false;
window.addEventListener('keydown', (e) => {
  if (e.code === 'Space' && !spaceDown && e.target === document.body) {
    e.preventDefault();
    spaceDown = true;
    canvas.style.cursor = 'grab';
  }
});
window.addEventListener('keyup', (e) => {
  if (e.code === 'Space') {
    spaceDown = false;
    canvas.style.cursor = 'default';
  }
});

canvas.addEventListener('mousedown', (e) => {
  if (spaceDown && e.button === 0) {
    state.panning = true;
    state.panStart = { x: e.clientX - state.camera.x, y: e.clientY - state.camera.y };
    canvas.style.cursor = 'grabbing';
    e.stopPropagation();
  }
}, true);

// ---- Init ----
window.addEventListener('resize', resizeCanvas);
resizeCanvas();
console.log('Diagram Viewer initialized. Shortcuts: V=Select, R=Rect, E=Ellipse, D=Diamond, T=Text, L=Line');
