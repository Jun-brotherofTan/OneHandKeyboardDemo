
from io import open
import pkg_resources
import setuptools
from setuptools import setup
from setuptools.command.install import install

# 判断paddle安装版本，对版本进行设置
install_requires = []
try:
    import paddle
    # 若版本太低，设置版本的更新
    if paddle.__version__ < '2.3':
        installed_packages = pkg_resources.working_set
        paddle_pkgs = [i.key for i in installed_packages if "paddle" in i.key]

        if "paddlepaddle-gpu" in paddle_pkgs:
            install_requires = ['paddlepaddle-gpu>=2.3']
        elif "paddlepaddle" in paddle_pkgs:
            install_requires = ['paddlepaddle>=2.3']

except ImportError:
    install_requires = ['paddlepaddle>=2.3']
try:
    import LAC
    # 若版本太低，设置版本的更新
    if LAC.version < '2.1':
        install_requires.append('LAC>=2.1')
except ImportError:
    install_requires.append('LAC>=2.1')

with open("README.md", "r", encoding='utf8') as fh:
    long_description = fh.read()
setup(
    name="ddparser",
    version="1.0.8",
    author="Baidu NLP",
    author_email="nlp-parser@baidu.com",
    description="A chinese dependency parser tool by Baidu NLP.",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/baidu/ddparser",
    install_requires=install_requires,
    python_requires=">=3.7",
    packages=setuptools.find_packages(),
    include_package_data=True,
    platforms="any",
    keywords=("ddparser chinese depencency parser"),
    license='Apache 2.0',
    classifiers=[
        'License :: OSI Approved :: Apache Software License',
        'Programming Language :: Python',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8',
    ],
)