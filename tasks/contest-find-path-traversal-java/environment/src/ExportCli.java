import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;

public final class ExportCli {
    private static final Path EXPORT_ROOT = Path.of("/app/exports");

    public static void saveExport(String requestedName, byte[] contents) throws IOException {
        if (!requestedName.endsWith(".csv")) {
            throw new IllegalArgumentException("CSV exports only");
        }
        Path destination = EXPORT_ROOT.resolve(requestedName);
        Files.createDirectories(destination.getParent());
        Files.write(destination, contents);
    }

    private ExportCli() {}
}
