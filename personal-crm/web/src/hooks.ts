import { useEffect, useState } from 'react';
import type { Api } from './api';
export function useLoad<T>(api:Api,path:string,revision=0) {
  const [state,setState]=useState<{data?:T;loading:boolean;error?:string}>({loading:true});
  useEffect(()=>{
    const abort=new AbortController();
    setState(current=>({...current,loading:true,error:undefined}));
    api<T>(path,'GET',undefined,abort.signal).then(data=>{if(!abort.signal.aborted)setState({data,loading:false});})
      .catch((error:Error)=>{if(!abort.signal.aborted)setState({loading:false,error:error.message});});
    return ()=>abort.abort();
  },[api,path,revision]);
  return state;
}
