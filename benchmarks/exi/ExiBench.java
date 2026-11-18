import com.siemens.ct.exi.core.*;
import com.siemens.ct.exi.core.grammars.Grammars;
import com.siemens.ct.exi.core.helpers.DefaultEXIFactory;
import com.siemens.ct.exi.grammars.GrammarFactory;
import com.siemens.ct.exi.main.api.sax.EXIResult;
import com.siemens.ct.exi.main.api.sax.EXISource;
import org.xml.sax.InputSource;
import org.xml.sax.XMLReader;
import javax.xml.parsers.SAXParserFactory;
import javax.xml.transform.*;
import javax.xml.transform.sax.SAXSource;
import javax.xml.transform.stream.StreamResult;
import java.io.*;
import java.nio.file.*;
import java.util.*;

public class ExiBench {
    static byte[] encode(EXIFactory f, byte[] xml) throws Exception {
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        EXIResult result = new EXIResult(f);
        result.setOutputStream(out);
        SAXParserFactory spf = SAXParserFactory.newInstance();
        spf.setNamespaceAware(true);
        XMLReader reader = spf.newSAXParser().getXMLReader();
        reader.setContentHandler(result.getHandler());
        reader.parse(new InputSource(new ByteArrayInputStream(xml)));
        return out.toByteArray();
    }

    static String decode(EXIFactory f, byte[] exi) throws Exception {
        EXISource source = new EXISource(f);
        XMLReader reader = source.getXMLReader();
        Transformer t = TransformerFactory.newInstance().newTransformer();
        StringWriter w = new StringWriter();
        t.transform(new SAXSource(reader, new InputSource(new ByteArrayInputStream(exi))), new StreamResult(w));
        return w.toString();
    }

    public static void main(String[] args) throws Exception {
        String xsd = args[0];
        Grammars schema = GrammarFactory.newInstance().createGrammars(xsd);
        for (int a = 1; a < args.length; a++) {
            File[] files = new File(args[a]).listFiles((d, n) -> n.endsWith(".xml"));
            Arrays.sort(files);
            List<byte[]> docs = new ArrayList<>();
            long xmlBytes = 0;
            for (File file : files) { byte[] b = Files.readAllBytes(file.toPath()); docs.add(b); xmlBytes += b.length; }
            System.out.printf("%s messages=%d xml_avg=%.1f%n", args[a], docs.size(), xmlBytes / (double) docs.size());
            for (String mode : new String[]{"schema+lexical", "schema+lexical+compression"}) {
                EXIFactory f = DefaultEXIFactory.newInstance();
                if (mode.startsWith("schema")) f.setGrammars(schema);
                if (mode.endsWith("compression")) f.setCodingMode(CodingMode.COMPRESSION);
                if (mode.contains("lexical")) f.getFidelityOptions().setFidelity(FidelityOptions.FEATURE_LEXICAL_VALUE, true);
                long total = 0; int failed = 0, decodedOk = 0;
                java.io.File outDir = new java.io.File(args[a] + "-" + mode);
                outDir.mkdirs();
                int index = 0;
                long start = System.nanoTime();
                for (byte[] doc : docs) {
                    try {
                        byte[] exi = encode(f, doc);
                        total += exi.length;
                        String back = decode(f, exi);
                        Files.write(new java.io.File(outDir, String.format("%05d.exi", index)).toPath(), exi);
                        Files.write(new java.io.File(outDir, String.format("%05d.back.xml", index)).toPath(), back.getBytes("UTF-8"));
                        index++;
                        if (back.length() > 0) decodedOk++;
                    } catch (Exception e) {
                        if (failed++ == 0) System.out.println("  first failure: " + e);
                    }
                }
                double ms = (System.nanoTime() - start) / 1e6;
                System.out.printf("  %-24s avg=%.1f B/msg  encoded=%d failed=%d decoded=%d  %.0f ms%n",
                        mode, total / (double) (docs.size() - failed), docs.size() - failed, failed, decodedOk, ms);
            }
        }
    }
}
