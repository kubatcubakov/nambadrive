const paths: Record<string,string> = {
  mine:'M5 3h10l4 4v14H5z M14 3v5h5 M8 12h8 M8 16h6',
  spaces:'M3 6h7l2 2h9v12H3z',
  departments:'M12 3v6 M5 14v-4h14v4 M2 15h6v6H2z M9 15h6v6H9z M16 15h6v6h-6z M9 2h6v6H9z',
  shared:'M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2 M9 3a4 4 0 1 0 0 8a4 4 0 0 0 0-8 M17 4a4 4 0 0 1 0 8 M22 21v-2a4 4 0 0 0-3-4',
  recent:'M12 3a9 9 0 1 0 0 18a9 9 0 0 0 0-18 M12 7v5l3 2',
  favorites:'m12 3 3 6 7 1-5 5 1 7-6-3-6 3 1-7-5-5 7-1z',
  requests:'M5 19 19 5 M6 5h13v13',
  reviews:'M5 12l4 4 10-10',
  trash:'M3 6h18 M9 6V3h6v3 M5 6l1 15h12l1-15 M10 10v7 M14 10v7',
  notifications:'M6 9a6 6 0 0 1 12 0v6l2 3H4l2-3z M10 21h4',
  search:'M10 3a7 7 0 1 0 0 14a7 7 0 0 0 0-14 M15 15l6 6',
  profile:'M12 3a4 4 0 1 0 0 8a4 4 0 0 0 0-8 M4 21v-2a8 8 0 0 1 16 0v2',
  administration:'M12 8a4 4 0 1 0 0 8a4 4 0 0 0 0-8 M10 2h4l1 3 3 1 3 3-1 3 1 3-3 3-3 1-1 3h-4l-1-3-3-1-3-3 1-3-1-3 3-3 3-1z',
};
export function Icon({name}:{name:string}) {
  return <svg className="ui-icon" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><path d={paths[name] ?? paths.mine}/></svg>
}
export function FileIcon({name,type}:{name:string;type:string}) {
  const folder=type!=='DOCUMENT'; const extension=name.split('.').at(-1)?.toUpperCase() ?? '';
  return <span className={`file-icon ${folder?'folder-icon':''}`} data-extension={extension} aria-hidden="true">{folder ? <svg viewBox="0 0 32 28" fill="currentColor"><path d="M2 4a3 3 0 0 1 3-3h8l3 4h11a3 3 0 0 1 3 3v15a3 3 0 0 1-3 3H5a3 3 0 0 1-3-3z"/></svg> : <><Icon name="mine"/><small>{extension.slice(0,4)}</small></>}</span>
}
