import express from 'express';
import { Low, JSONFile } from 'lowdb';
import bodyParser from 'body-parser';
import cors from 'cors';

const app = express();
app.use(cors());
app.use(bodyParser.json());

const db = new Low(new JSONFile('db.json'));
await db.read();
if (!db.data) db.data = { pages: [] };

app.get('/pages', (req,res)=> res.json(db.data.pages));
app.get('/pages/:id', (req,res)=>{
  const p = db.data.pages.find(x=>x.id===req.params.id);
  res.json(p||{});
});
app.post('/pages', async (req,res)=>{
  const id = Date.now().toString();
  const p = { id, title:req.body.title||'Untitled', content:req.body.content||'' };
  db.data.pages.push(p);
  await db.write();
  res.json(p);
});
app.put('/pages/:id', async (req,res)=>{
  const i = db.data.pages.findIndex(x=>x.id===req.params.id);
  if(i<0) return res.status(404).send('Not found');
  db.data.pages[i] = { ...db.data.pages[i], ...req.body };
  await db.write();
  res.json(db.data.pages[i]);
});
app.listen(4000, ()=> console.log('Backend running http://localhost:4000'));