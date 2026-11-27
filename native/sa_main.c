/* sa_main.c - Senjin Aleste, native port (static recompilation): host entry point.
 * Usage: senjin_aleste [game_dir] [-v|-vv]   (folder containing senxin_aleste_apm3.exe and windata/)
 *        senjin_aleste --gl-probe           create a hidden OpenGL context and print the renderer */
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <signal.h>
#include <SDL2/SDL.h>
#include <GL/gl.h>
#include "sa_host.h"
#include "version.h"

void k32_register(void); void ole_register(void); void user32_register(void); void misc_register(void); void d3d9_register(void); void bcrypt_register(void); void dinput_register(void); void gdi_register(void);
void imports_report(void);
extern void call_ind(uint32_t);
static void on_usr1(int s) { (void)s; imports_report(); }
static void on_term(int s) { (void)s; _exit(130); }

/* --gl-probe: the Flatpak launcher asks whether the selected Mesa driver (for
 * example zink) can really create the OpenGL 3.3 context before starting the
 * game.  It prints "renderer / version" and returns 0, or an error and 1. */
static int gl_probe(void) {
    if (SDL_Init(SDL_INIT_VIDEO) != 0) {
        fprintf(stderr, "SDL_Init: %s\n", SDL_GetError());
        return 1;
    }
    SDL_GL_SetAttribute(SDL_GL_CONTEXT_MAJOR_VERSION, 3);
    SDL_GL_SetAttribute(SDL_GL_CONTEXT_MINOR_VERSION, 3);
    SDL_GL_SetAttribute(SDL_GL_CONTEXT_PROFILE_MASK, SDL_GL_CONTEXT_PROFILE_CORE);
    SDL_GL_SetAttribute(SDL_GL_DOUBLEBUFFER, 1);
    SDL_Window *win = SDL_CreateWindow("Senjin Aleste", SDL_WINDOWPOS_UNDEFINED,
        SDL_WINDOWPOS_UNDEFINED, 64, 64, SDL_WINDOW_OPENGL | SDL_WINDOW_HIDDEN);
    if (!win) {
        fprintf(stderr, "SDL_CreateWindow: %s\n", SDL_GetError());
        SDL_Quit();
        return 1;
    }
    SDL_GLContext ctx = SDL_GL_CreateContext(win);
    if (!ctx) {
        fprintf(stderr, "SDL_GL_CreateContext: %s\n", SDL_GetError());
        SDL_DestroyWindow(win);
        SDL_Quit();
        return 1;
    }
    const GLubyte *r = glGetString(GL_RENDERER), *v = glGetString(GL_VERSION);
    printf("%s / %s\n", r ? (const char *)r : "?", v ? (const char *)v : "?");
    SDL_GL_DeleteContext(ctx);
    SDL_DestroyWindow(win);
    SDL_Quit();
    return 0;
}

int main(int argc, char **argv) {
    const char *dir = ".";
    int probe = 0;
    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "-v")) sa_verbose = 1;
        else if (!strcmp(argv[i], "-vv")) sa_verbose = 2;
        else if (!strcmp(argv[i], "--gl-probe")) probe = 1;
        else dir = argv[i];
    }
    if (probe) return gl_probe();
    sa_log("Senjin Aleste native - version %s", SALE_VERSION_FULL);
    if (chdir(dir)) sa_fatal("game folder not found: %s", dir);
    snprintf(sa_game_dir, sizeof sa_game_dir, "%s", dir);
    { void config_sync(void); config_sync(); }
    mem_init();
    k32_register(); ole_register(); user32_register(); misc_register(); d3d9_register(); bcrypt_register(); dinput_register(); gdi_register();
    uint32_t entry = pe_load("senxin_aleste_apm3.exe");
    thread_setup_current(0);
    wr32(cpu.fs_base + 0x24, 1000);
    atexit(imports_report); signal(SIGUSR1, on_usr1); signal(SIGINT, on_term); signal(SIGTERM, on_term);
    push32(0xFFFFFFF0u);           /* return from the entry point: end */
    call_ind(entry);
    sa_log("entry point finished, eax=%u", cpu.eax);
    return (int)cpu.eax;
}
