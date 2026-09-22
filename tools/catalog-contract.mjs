#!/usr/bin/env node
import {execFileSync} from 'node:child_process';
import {readFile,lstat,readdir,realpath} from 'node:fs/promises';
import {resolve,relative,sep} from 'node:path';
import {fileURLToPath} from 'node:url';

const entryFields=new Set(['id','file','title','description','body','settings','model','output','tags','status','notes','publishedAt','coverImage','difficulty','inputs','outputs']);
const bodyLimit=20000;
// Bodies publish without review; raw HTML is rejected at the source, not left to the renderer.
const htmlTag=/<\/?[a-z!][^>]*>/i;
const plain=(value,max)=>nonempty(value)&&value.length<=max&&!htmlTag.test(value);
// Recommended settings: ordered label/value pairs; a value is one string or a short list of alternatives.
function validSettings(settings){
 if(!Array.isArray(settings)||!settings.length||settings.length>40)return false;
 const labels=new Set();
 for(const item of settings){
  if(!isObject(item)||Object.keys(item).some(key=>!['label','value'].includes(key))||!plain(item.label,60)||labels.has(item.label.trim().toLowerCase()))return false;
  labels.add(item.label.trim().toLowerCase());
  const values=Array.isArray(item.value)?item.value:[item.value];
  if(!values.length||values.length>12||new Set(values).size!==values.length||values.some(value=>!plain(value,Array.isArray(item.value)?80:300)))return false;
 }
 return true;
}
const media=new Set(['Text','Image','Video','Audio','Reference pack']);
const isObject=value=>value!==null&&typeof value==='object'&&!Array.isArray(value);
const nonempty=value=>typeof value==='string'&&value.trim().length>0;
const safePath=value=>nonempty(value)&&!value.startsWith('/')&&!value.split('/').some(part=>!part||part==='.'||part==='..'||part.includes('\\'));
const list=value=>Array.isArray(value)&&value.length>0&&value.every(nonempty);
function fail(message){throw Error(`Invalid workflow catalogue: ${message}`);}

export function validateCatalog(value,{baseCatalog,now=new Date()}={}){
 if(!isObject(value)||Object.keys(value).some(key=>!['schemaVersion','workflows'].includes(key))||value.schemaVersion!==1||!Array.isArray(value.workflows))fail('expected schemaVersion 1 and workflows array');
 if(Number.isNaN(new Date(now).getTime()))fail('invalid validation time');
 const baseEntries=Array.isArray(baseCatalog?.workflows)?baseCatalog.workflows:[],baseById=new Map(baseEntries.map(item=>[item.id,item])),baseByFile=new Map(baseEntries.map(item=>[item.file,item]));
 const ids=new Set(),files=new Set();
 for(const entry of value.workflows){
  if(!isObject(entry)||Object.keys(entry).some(key=>!entryFields.has(key)))fail('entry has unknown fields');
  for(const key of ['id','file','title','description','model','output'])if(!nonempty(entry[key]))fail(`${key} must be nonempty`);
  if(!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(entry.id)||ids.has(entry.id))fail(`duplicate or invalid id: ${entry.id}`);ids.add(entry.id);
  if(!safePath(entry.file)||!entry.file.startsWith('workflows/')||!entry.file.endsWith('.json')||files.has(entry.file))fail(`duplicate or unsafe workflow path: ${entry.file}`);files.add(entry.file);
  if(entry.status!=='published')fail(`${entry.id} must be published`);
  if(!['Beginner','Advanced'].includes(entry.difficulty))fail(`${entry.id} has invalid difficulty`);
  for(const key of ['inputs','outputs'])if(!Array.isArray(entry[key])||!entry[key].length||new Set(entry[key]).size!==entry[key].length||entry[key].some(item=>!media.has(item)))fail(`${entry.id} has invalid ${key}`);
  if(!list(entry.tags)||entry.notes!==undefined&&(!Array.isArray(entry.notes)||entry.notes.some(note=>!nonempty(note))))fail(`${entry.id} has invalid tags or notes`);
  if(entry.body!==undefined&&(!nonempty(entry.body)||entry.body.length>bodyLimit||htmlTag.test(entry.body)))fail(`${entry.id} body must be nonempty Markdown under ${bodyLimit} characters without HTML tags`);
  if(entry.settings!==undefined&&!validSettings(entry.settings))fail(`${entry.id} settings must be 1-40 unique plain-text labels, each with one value or a list of up to 12 distinct values`);
  if(entry.coverImage!==undefined&&(!safePath(entry.coverImage)||! /^catalog\/assets\/.+\.(?:webp|png|jpe?g)$/i.test(entry.coverImage)))fail(`${entry.id} has unsafe coverImage`);
  const base=baseById.get(entry.id),sameFileBase=baseByFile.get(entry.file);if(sameFileBase&&sameFileBase.id!==entry.id)fail(`stable id changed for ${entry.file}`);
  if(base?.publishedAt){if(entry.publishedAt!==base.publishedAt)fail(`${entry.id} publishedAt is immutable`);}
  else if(!base&&!entry.publishedAt)fail(`${entry.id} requires publishedAt`);
  if(entry.publishedAt!==undefined){const date=new Date(entry.publishedAt);if(!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{3})?Z$/.test(entry.publishedAt)||Number.isNaN(date.getTime())||date.getTime()>new Date(now).getTime())fail(`${entry.id} has invalid or future publishedAt`);}
 }
 return value;
}

async function regularInside(root,path,{maxBytes,kind}){const absolute=resolve(root,path),rel=relative(root,absolute);if(rel.startsWith('..'+sep)||rel==='..'||rel.startsWith(sep))fail(`${kind} escapes repository: ${path}`);let current=root;for(const part of path.split('/')){current=resolve(current,part);let component;try{component=await lstat(current);}catch{fail(`missing ${kind}: ${path}`);}if(component.isSymbolicLink())fail(`${kind} path contains a symlink: ${path}`);}const stat=await lstat(absolute);if(!stat.isFile())fail(`${kind} must be a regular file: ${path}`);if(maxBytes&&stat.size>maxBytes)fail(`${kind} exceeds ${maxBytes} bytes: ${path}`);const actual=await realpath(absolute),actualRel=relative(root,actual);if(actualRel.startsWith('..'+sep)||actualRel==='..')fail(`${kind} resolves outside repository: ${path}`);return absolute;}
async function workflowFiles(root,dir='workflows'){const output=[];async function walk(relativeDir){const absolute=resolve(root,relativeDir);for(const item of await readdir(absolute,{withFileTypes:true})){const path=`${relativeDir}/${item.name}`;if(item.isSymbolicLink())fail(`workflow path is a symlink: ${path}`);if(item.isDirectory())await walk(path);else if(item.isFile()&&item.name.endsWith('.json'))output.push(path);}}try{await walk(dir);}catch(error){if(error?.code==='ENOENT')fail('missing workflows directory');throw error;}return output.sort();}
export async function validateRepository(root,{baseCatalog,now}={}){
 root=await realpath(resolve(root));const catalogPath=await regularInside(root,'catalog.json',{maxBytes:5*1024*1024,kind:'catalog'});let catalog;try{catalog=JSON.parse(await readFile(catalogPath,'utf8'));}catch{fail('catalog.json is not valid JSON');}validateCatalog(catalog,{baseCatalog,now});
 const disk=await workflowFiles(root),declared=[...catalog.workflows.map(item=>item.file)].sort();if(JSON.stringify(disk)!==JSON.stringify(declared))fail('every workflow JSON must have exactly one catalogue entry');
 for(const entry of catalog.workflows){const path=await regularInside(root,entry.file,{maxBytes:5*1024*1024,kind:'workflow'});let graph;try{graph=JSON.parse(await readFile(path,'utf8'));}catch{fail(`workflow is not valid JSON: ${entry.file}`);}if(!isObject(graph)||!Array.isArray(graph.nodes)||!graph.nodes.length)fail(`workflow graph requires nonempty nodes: ${entry.file}`);if(entry.coverImage)await regularInside(root,entry.coverImage,{maxBytes:5*1024*1024,kind:'cover image'});}
 return catalog;
}

if(process.argv[1]&&resolve(process.argv[1])===fileURLToPath(import.meta.url)){
 const args=process.argv.slice(2),rootIndex=args.indexOf('--root'),baseIndex=args.indexOf('--base-ref');if(rootIndex<0||!args[rootIndex+1]||baseIndex<0||!args[baseIndex+1])throw Error('Usage: catalog-check --root DIR --base-ref SHA');const root=resolve(args[rootIndex+1]),baseRef=args[baseIndex+1];if(!/^[a-f0-9]{40}$/.test(baseRef))throw Error('Base reference must be an exact commit SHA');let baseCatalog;try{baseCatalog=JSON.parse(execFileSync('git',['show',`${baseRef}:catalog.json`],{cwd:root,encoding:'utf8',stdio:['ignore','pipe','pipe']}));}catch{throw Error('Unable to load base catalogue');}const catalog=await validateRepository(root,{baseCatalog});console.log(`Validated ${catalog.workflows.length} published workflows.`);
}
