@ECHO OFF
setlocal

set SPHINXBUILD=python -m sphinx
set SOURCEDIR=docs/sphinx
set BUILDDIR=docs/sphinx/_build

if "%1" == "" goto help

%SPHINXBUILD% -b %1 %SOURCEDIR% %BUILDDIR%/%1
goto end

:help
echo 用法: make.bat html

:end
endlocal
