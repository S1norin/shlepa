package com.example;
import com.example.service.UrlPreviewService;
import com.sun.net.httpserver.HttpServer;
import org.junit.*;
import java.net.*;
import java.nio.file.*;
import java.util.concurrent.atomic.AtomicBoolean;
public class SecurityTest {
 private HttpServer server; private AtomicBoolean hit;
 @Before public void start() throws Exception {hit=new AtomicBoolean(false);server=HttpServer.create(new InetSocketAddress("127.0.0.1",0),0);server.createContext("/secret",x->{hit.set(true);byte[] b="INTERNAL_SECRET".getBytes();x.sendResponseHeaders(200,b.length);x.getResponseBody().write(b);x.close();});server.start();}
 @After public void stop(){server.stop(0);}
 @Test public void blocksLoopbackAndAlternateForms(){int p=server.getAddress().getPort();String[] hosts={"127.0.0.1","localhost","2130706433","0x7f000001","[::1]","[::ffff:127.0.0.1]"};for(String h:hosts){hit.set(false);new UrlPreviewService().getUrlContentPreview("http://"+h+":"+p+"/secret");Assert.assertFalse("connected to "+h,hit.get());}}
 @Test public void blocksFileScheme() throws Exception {Path p=Files.createTempFile("secret","txt");Files.writeString(p,"FILE_SECRET");String r=new UrlPreviewService().getUrlContentPreview(p.toUri().toString());Assert.assertFalse(r.contains("FILE_SECRET"));}
 @Test public void blocksCredentials(){int p=server.getAddress().getPort();new UrlPreviewService().getUrlContentPreview("http://safe.example@127.0.0.1:"+p+"/secret");Assert.assertFalse(hit.get());}
}
