package com.example;
import com.example.service.UrlPreviewService;
import org.junit.*;
import java.io.*;
import java.net.*;
public class FunctionalTest {
 @BeforeClass public static void fakePublicHttp() { URL.setURLStreamHandlerFactory(protocol -> "http".equals(protocol) ? new URLStreamHandler(){protected URLConnection openConnection(URL u){return new URLConnection(u){public void connect(){} public InputStream getInputStream(){return new ByteArrayInputStream("line1\nPUBLIC_PREVIEW\nline3".getBytes());}};}} : null); }
 @Test public void previewsPublicHttp() { String r=new UrlPreviewService().getUrlContentPreview("http://8.8.8.8/article"); Assert.assertTrue(r,r.contains("PUBLIC_PREVIEW")); }
 @Test public void malformedInputReturnsError() { Assert.assertTrue(new UrlPreviewService().getUrlContentPreview("not a url").startsWith("Error")); }
}
