#!/usr/bin/env bash
set -euo pipefail
python3 - <<'PY'
from pathlib import Path
Path('/app/src/main/java/com/example/service/UrlPreviewService.java').write_text(r'''package com.example.service;
import java.io.*; import java.net.*; import java.nio.charset.StandardCharsets; import java.util.stream.Collectors;
public class UrlPreviewService {
 public String getUrlContentPreview(String raw){
  try { URL u=new URL(raw); String scheme=u.getProtocol().toLowerCase(); if(!scheme.equals("http")&&!scheme.equals("https")||u.getUserInfo()!=null) throw new SecurityException("URL rejected");
   InetAddress[] addresses=InetAddress.getAllByName(u.getHost()); if(addresses.length==0) throw new SecurityException("unresolved"); for(InetAddress a:addresses) reject(a);
   URLConnection c=u.openConnection(); c.setConnectTimeout(2000);c.setReadTimeout(2000); if(c instanceof HttpURLConnection)((HttpURLConnection)c).setInstanceFollowRedirects(false);
   try(BufferedReader r=new BufferedReader(new InputStreamReader(c.getInputStream(),StandardCharsets.UTF_8))){return r.lines().limit(5).collect(Collectors.joining("\n"));}
  }catch(Exception e){return "Error fetching content from URL: "+e.getMessage();}
 }
 private static void reject(InetAddress a){byte[] b=a.getAddress();boolean mapped=b.length==16;for(int i=0;mapped&&i<10;i++)mapped=b[i]==0;mapped=mapped&&b[10]==(byte)255&&b[11]==(byte)255;if(mapped){try{a=InetAddress.getByAddress(new byte[]{b[12],b[13],b[14],b[15]});}catch(Exception e){throw new SecurityException(e);}}
  if(a.isAnyLocalAddress()||a.isLoopbackAddress()||a.isLinkLocalAddress()||a.isSiteLocalAddress()||a.isMulticastAddress())throw new SecurityException("private destination");
 }
}''')
PY
